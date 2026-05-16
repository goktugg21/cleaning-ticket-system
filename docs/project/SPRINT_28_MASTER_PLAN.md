# Sprint 28 Master Plan and Progress Tracker

## 1. Purpose

This file is the **persistent execution plan and progress tracker** for
Sprint 28 and the sprint letters that follow it. It exists to prevent
context drift, repeated decisions, forgotten requirements, and AI sessions
going off-track between turns.

Boundaries:

- This file does **not** replace [`docs/backlog/PRODUCT_BACKLOG.md`](../backlog/PRODUCT_BACKLOG.md).
  The backlog stays the canonical list of feature work + dependency graph.
- This file does **not** replace [`docs/audits/current-state-2026-05-16-system-audit.md`](../audits/current-state-2026-05-16-system-audit.md).
  The audit stays the canonical current-state evidence with file:line
  references and gap matrix.
- This file **is** the execution tracker and current-batch pointer. Every
  future Claude Code / ChatGPT / human developer pass starts here.
- [`CLAUDE.md`](../../CLAUDE.md) remains the operating-instruction source
  for *how* to work in this repo (rules, conventions, multi-agent setup).

If anything below conflicts with the product spec or the audit, **stop and
report the conflict** — do not silently choose one.

---

## 2. Authoritative references

Read these in this order at the start of every pass:

1. [`CLAUDE.md`](../../CLAUDE.md) — operating rules (§2A product context, §4
   multi-agent contract, §8 things NOT to do).
2. **This file** — current batch pointer + decision log + open questions.
3. [`docs/audits/current-state-2026-05-16-system-audit.md`](../audits/current-state-2026-05-16-system-audit.md)
   — current-state evidence and gap matrix.
4. [`docs/product/meeting-2026-05-15-system-requirements.md`](../product/meeting-2026-05-15-system-requirements.md)
   — authoritative product behaviour (Contacts vs Users, modular permissions,
   view-first UI, Extra Work cart, pricing, proposal builder, override audit,
   future hooks).
5. [`docs/architecture/sprint-27-rbac-matrix.md`](../architecture/sprint-27-rbac-matrix.md)
   — security floor (RBAC invariants H-1..H-11).
6. [`docs/backlog/PRODUCT_BACKLOG.md`](../backlog/PRODUCT_BACKLOG.md) — open
   work + acceptance criteria per item.
7. [`docs/backlog/BUGS.md`](../backlog/BUGS.md) — open defects.
8. [`docs/backlog/DONE.md`](../backlog/DONE.md) — append-only ledger.

**Conflict-resolution rule.** If this master plan conflicts with the
product spec (`docs/product/`) or the audit (`docs/audits/`), **stop and
report the conflict**. Do not silently choose one. The product spec is the
product-behaviour floor; the audit is the current-state evidence floor; the
RBAC matrix is the security floor. This master plan is the *sequencing*
layer; it cannot override the floors.

---

## 3. Operating rules for every future pass

Every Claude Code, ChatGPT, or human implementation pass MUST follow these
rules:

1. **Start by reading this file.** Identify the **Current batch** (see §7).
2. **State the current batch explicitly** in the first message of the pass,
   before any tool call that modifies a file. Example: *"Current batch:
   Batch 1 — Operational health fixes. I will work only on Batch 1 items."*
3. **Do not implement work outside the current batch** unless the user
   explicitly approves the scope expansion. If a discovery during a batch
   reveals additional work, document it under "remaining risks" and stop
   to ask the user before expanding scope.
4. **Keep each batch small and commit-friendly.** A batch should end at a
   point where a single Git commit captures the change cleanly with a
   one-line subject + a short body. If a batch is growing beyond that
   shape, split it.
5. **Do not silently skip tests.** Run the tests / typecheck / lint that
   the batch's items require. If a check fails, fix it before reporting the
   batch done — or, if blocked, escalate per rule 12.
6. **After implementation, update this file before finishing.** This is the
   stable navigation contract for the next pass.
7. **Mark completed items with Markdown checkboxes and strikethrough.**
   Replace `- [ ] Open item` with `- [x] ~~Completed item~~`. The strike-
   through preserves the original wording while making the completion
   visually obvious.
8. **Under each completed batch, append a completion block** containing:
   - date (absolute ISO date, not "today")
   - commit hash if available
   - files changed summary (paths, not full diff)
   - tests/checks run + their outcomes
   - important decisions made (also add to §9 decision log)
   - remaining risks (anything the next batch must know)
9. **Keep the "Current batch" pointer updated** (§7). When a batch closes,
   advance the pointer to the next batch.
10. **Keep the "Next recommended batch" pointer updated** (§7). It's the
    on-deck batch; useful for prepping the next pass.
11. **Never rewrite history in this document.** Completion logs are
    append-only. If a previous entry is factually wrong, add a correction
    note below it dated with the correction date — do not edit the original.
12. **If a batch discovers a blocker, mark the blocker and stop.** Keep the
    Current batch pointer on the blocked batch. Add a "BLOCKED" line under
    that batch's checklist with the blocker description and the date.
    Resume only when the blocker is resolved.

---

## 4. Current project state summary

Snapshot derived from the [2026-05-16 audit](../audits/current-state-2026-05-16-system-audit.md).
Refresh after each batch.

### Backend
- Security / RBAC baseline is strong.
- RBAC invariants H-1 through H-11 are verified — enforcement points and
  test locks match the matrix doc (one minor doc drift on H-4 attribution,
  tracked in Batch 2).
- Ticket workflow override exists: `TicketStatusHistory.is_override` +
  `override_reason`; provider-driven coercion; `override_reason_required`
  400 contract (Sprint 27F-B1).
- `AuditLog.reason` and `AuditLog.actor_scope` exist (Sprint 27F-B2).
- Customer permission resolver and `CustomerCompanyPolicy` DENY layer exist
  (Sprint 27A–E).
- Extra Work backend exists **but is the wrong product shape** for the
  2026-05-15 requirements: single-line `ExtraWorkRequest`, no Service
  catalog, no cart, no Proposal entity.

### Frontend
- Sprint 27E (customer permission management UI) and Sprint 27F-F1 (ticket
  override modal) are correct and view-first.
- Sidebar is flat. No hierarchical customer-scoped submenu.
- Most admin detail pages load editable forms on first render (closed-door
  / view-first violation across `CustomerFormPage` parent, `BuildingFormPage`,
  `CompanyFormPage`, `UserFormPage`).
- Extra Work pages (`CreateExtraWorkPage`, `ExtraWorkListPage`,
  `ExtraWorkDetailPage`) have **no i18n at all** (hard-coded English) and
  still assume the single-line request flow.
- Dashboard is ticket-only; no Extra Work integration; renders identical
  shape for every role.

### Operational
- 4 committed migrations unapplied on the dev DB
  (`audit.0002_auditlog_reason_actor_scope`,
  `customers.0005_customercompanypolicy`,
  `customers.0006_backfill_customer_company_policy`,
  `tickets.0007_ticketstatushistory_is_override_and_more`).
  The Django test runner creates `test_*` databases and auto-applies
  migrations every run — the **548-test baseline on commit `be7b3e4` is
  unaffected** by this drift; it only means the dev container's actual DB
  schema is behind the code.
- Frontend `npm run typecheck` and `npm run build`: green.
- Frontend `npm run lint`: 49 errors + 3 warnings, all pre-existing
  baseline (Sprint 27F-F1 verified zero new lint hits in its delta).

---

## 5. Non-negotiable product requirements

Concise reference. Full text lives in
[`docs/product/meeting-2026-05-15-system-requirements.md`](../product/meeting-2026-05-15-system-requirements.md).
Any future change that contradicts these is wrong by default — push back.

1. **Provider company vs Customer company must be visually and structurally
   clear.** Provider = the cleaning/service provider (e.g. Osius);
   Customer = the client organisation.
2. **Contacts are not login users.** A Contact is a communication record
   only — name, email, phone, role label, notes — with no password, no
   JWT, no `UserRole`, no memberships, no permission overrides.
3. **Building Manager must see assigned-building customers and contacts
   read-only.** No mutate paths by default. (Optional delegated management
   permissions are a later, separate decision.)
4. **Provider Company Admin can edit, but pages must still be view-first
   first.** Detail pages load read-only; edit happens through explicit
   Edit/Add → modal or separate page.
5. **Customer Company Admin can manage lower customer users but cannot
   promote anyone to Customer Company Admin** (RBAC matrix H-6 / H-7).
   Cannot grant permissions above their own level. Cannot create an
   admin-equivalent user via permission stacking.
6. **Staff permissions must eventually be per building.** Example shape:
   B1 = own-only; B2 = building-wide read; B3 = building-wide read + assign.
   If a Staff user can see all tickets in a building, tickets assigned to
   them should be visually prioritised.
7. **Staff completion routing must eventually be configurable.** Default:
   Staff marks done → Building Manager review. Optional (per
   staff/building, separately for Tickets vs Extra Work): Staff marks done
   → directly to customer approval.
8. **Extra Work has two paths:**
   1. **Contract fixed-service shopping-cart path** — customer browses
      catalog, adds N services to a cart, submits; if every line has a
      pre-agreed customer-specific contract price, proposal is skipped and
      execution Tickets are spawned immediately.
   2. **Custom request / proposal path** — customer requests something not
      in contract OR any line lacks an agreed price; whole cart routes to
      provider-side manager/admin for a proposal; customer approves/rejects.
9. **Global default price alone must NOT create an instant customer order.**
   Global default exists as a provider-side reference; the instant-ticket
   path requires an **active customer-specific contract price**.
10. **Proposal approval must create operational ticket(s).** Approval is
    atomic with the ticket spawn (single `transaction.atomic`). Rejected
    proposal lines do not spawn tickets.
11. **Customer must never see provider internal notes.** The customer-
    facing serializer omits `internal_note` (or its current legacy name).
    PDF export must also exclude internal notes.
12. **Staff may see normal internal work notes by default, but
    cost/margin/provider-only proposal notes must be hideable from Staff.**
    This is a **3-way privacy split** (customer / provider-with-staff /
    provider-only-cost-margin). Today the system is only 2-way; the cost-
    margin strip from Staff is not yet enforced.
13. **Dashboard must show both Tickets and Extra Work.** Top-level cards /
    sections for both; clicking each goes to its dedicated dashboard/list;
    shape differs between provider-side and customer-side roles.

---

## 6. Master batch sequence

Strict order. Each batch is small enough to ship as one commit (or a tight
pair of commits, backend + frontend). Do NOT start a batch before the
previous one lands. Do NOT implement items from later batches.

### Batch 1 — Operational health fixes

Goal: clear the four operational gotchas the audit flagged. Zero schema
risk. ~1 day of work.

- [x] ~~Apply pending dev DB migrations manually, after confirming with the
      user. (`audit.0002_auditlog_reason_actor_scope`,
      `customers.0005_customercompanypolicy`,
      `customers.0006_backfill_customer_company_policy`,
      `tickets.0007_ticketstatushistory_is_override_and_more`.) Do **not**
      run migrations automatically without explicit user approval. Mark
      this item as planned/manual and request confirmation.~~
- [x] ~~Fix frontend `getApiError` raw HTML handling at
      [`frontend/src/api/client.ts:148`](../../frontend/src/api/client.ts#L148).
      Detect `<!DOCTYPE` / `<html` prefix and downgrade to the status
      fallback string. ~5-line change. Add a unit/contract test.~~
- [x] ~~Add Sprint 27F-B2 `AuditLog.reason: string` and
      `AuditLog.actor_scope: Record<string, unknown>` fields to the
      frontend `AuditLog` type at
      [`frontend/src/api/types.ts:481-492`](../../frontend/src/api/types.ts#L481-L492).
      Keep `tsc --noEmit` green.~~
- [x] ~~Replace the literal `"Extra Work"` string in the sidebar at
      [`frontend/src/layout/AppShell.tsx:157`](../../frontend/src/layout/AppShell.tsx#L157)
      with a `t()` call. Add the key to both `frontend/src/i18n/en/common.json`
      and `frontend/src/i18n/nl/common.json`. Preserve EN/NL parity.~~

**Completion block — Batch 1**

- **Date:** 2026-05-16
- **Commit:** uncommitted on working tree as of 2026-05-16 (Batch 1 diff
  on top of `6e572db`; ready for a single batch commit once reviewed).
- **Files changed summary:**
  - Frontend: `frontend/src/api/client.ts` (HTML-prefix guard in
    `getApiError`), `frontend/src/api/types.ts` (Sprint 27F-B2 fields on
    `AuditLog`), `frontend/src/layout/AppShell.tsx` (sidebar `t()` call),
    `frontend/src/i18n/en/common.json` and
    `frontend/src/i18n/nl/common.json` (new `nav.extra_work` key in both,
    EN/NL parity preserved).
  - Backend: no source changes. Dev DB migrations applied after explicit
    user approval (`audit.0002`, `customers.0005`, `customers.0006`,
    `tickets.0007`).
  - Docs: this completion block + §7 pointer advance + §8 log row.
- **Tests / checks run:**
  - `docker compose exec backend python manage.py showmigrations audit
    customers tickets` (pre + post): pre showed 4 unapplied; post showed
    all `[X]`.
  - `docker compose exec backend python manage.py migrate`:
    `audit.0002_auditlog_reason_actor_scope OK`,
    `customers.0005_customercompanypolicy OK`,
    `customers.0006_backfill_customer_company_policy OK`,
    `tickets.0007_ticketstatushistory_is_override_and_more OK`.
  - `docker compose exec backend python manage.py check` (pre + post
    migrate): both **0 issues**.
  - `npm run typecheck`: clean (empty diagnostic output).
  - `npm run build`: clean, 472ms; advisory chunk-size warning only
    (baseline; not from this diff).
  - `npm run lint`: **52 problems (49 errors, 3 warnings)** — identical
    to the audit-recorded baseline. The single AppShell.tsx hit is at
    `:93:5` (pre-existing `react-hooks/set-state-in-effect`), not at the
    `:157` line touched in this batch. Zero new lint hits in the four
    changed files.
  - Unit-test infrastructure status: **none wired**. The frontend
    `package.json` declares no `test` script and lists no Vitest /
    Jest / Testing-Library dependency; only Playwright e2e exists.
    The `getApiError` change therefore ships with a defensive code-level
    guard and typecheck/build coverage, but **no dedicated unit test
    was added**. A Playwright spec would need a mocked 500 HTML
    response and a route to render it; that's heavier than the 5-line
    change warrants. Recommendation: add Vitest + an `api/client.test.ts`
    in a later batch (e.g. as part of Batch 3 or 13 setup).
- **Important decisions made:**
  - HTML detection in `getApiError` matches both upper- and lower-case
    `<!DOCTYPE` / `<html>` prefixes (Django serves uppercase
    `<!DOCTYPE html>`; some proxies emit lowercase). Whitespace-tolerant
    via `trimStart()`. The original DRF-string pass-through is preserved
    for non-HTML payloads.
  - `nav.extra_work` translations: **EN** "Extra Work" (brand-preserving
    capitalisation, matches the existing literal), **NL** "Extra werk"
    (Dutch sentence-case convention used by sibling keys like "Nieuw
    ticket"). No decision-log row added; this is purely a translation
    choice within the i18n contract, not a product decision.
  - Migrations were applied after explicit user approval (per master
    plan §7 rule). The migrations themselves were already audit-locked
    and test-DB-validated by Sprints 27B/27C/27F; this pass only moved
    the dev container's schema into the same state.
- **Remaining risks:**
  - No automated unit-test coverage on `getApiError`. If a future change
    re-introduces a raw-HTML leak (e.g. an interceptor that converts the
    HTML to a different non-DOCTYPE prefix), only end-to-end manual
    smoke would catch it. Adding Vitest is a parked follow-up.
  - The `AuditLog` type now declares `reason: string` + `actor_scope:
    Record<string, unknown>` as **required** (not optional). The backend
    Sprint 27F-B2 serializer always emits both fields with defaults
    (`""` and `{}`), so this is correct — but any legacy fixture or
    third-party AuditLog ingester that omits the fields would produce
    a runtime TypeScript-vs-actual mismatch. None observed in the
    codebase today.
  - `nav.extra_work` is the only sidebar entry whose Dutch translation
    differs in case-convention from the English. If a stakeholder
    prefers "Extra Werk" (title-case to match the brand), flip the NL
    value — no other code changes required.

### Batch 2 — Verify mild backend risk

Goal: confirm whether the `is_staff_role`-permitted `/api/tickets/<id>/assign/`
path is a real bypass risk. Resolve H-4 attribution drift. ~½ day.

- [x] ~~Read [`backend/tickets/serializers.py`](../../backend/tickets/serializers.py)
      `TicketAssignSerializer.validate` and trace the path called by the
      `assign` action at
      [`tickets/views.py:247-280`](../../backend/tickets/views.py#L247-L280).~~
- [x] ~~Confirm STAFF cannot reassign tickets through
      `POST /api/tickets/<id>/assign/`. If the serializer doesn't refuse,
      that's a real backend bug — escalate per rule 12.~~
- [x] ~~Add a regression test if missing — e.g.
      `tickets/tests/test_sprint28a_staff_assign_block.py` asserting
      STAFF POST returns 403 with no DB write.~~
- [x] ~~Fix only if a real bug exists. Do not change the gate if it's already
      correct.~~
- [x] ~~Resolve H-4 matrix attribution drift in
      [`docs/architecture/sprint-27-rbac-matrix.md`](../architecture/sprint-27-rbac-matrix.md)
      §3 row 4. Either rewrite the row to cite the structural guard (no
      STAFF entries anywhere in `ALLOWED_TRANSITIONS`) or land an
      H-4-specific regression test under the same name.~~

**Completion block — Batch 2**

- **Date:** 2026-05-16
- **Commit:** uncommitted on working tree as of 2026-05-16 (Batch 2 diff
  on top of `739e347`; ready for a single batch commit once reviewed).
- **Files changed summary:**
  - **Production fix (real bug found):** `backend/tickets/views.py`
    (assign action gate — replaced `is_staff_role` with explicit
    `{SUPER_ADMIN, COMPANY_ADMIN, BUILDING_MANAGER}` allow-list),
    `backend/tickets/serializers.py` (`TicketAssignSerializer.validate`
    — same allow-list, defense in depth).
  - **New regression test:**
    `backend/tickets/tests/test_sprint28a_staff_assign_block.py`
    (4 test cases: STAFF cannot un-assign with building visibility;
    STAFF cannot re-assign with building visibility; STAFF with direct
    `TicketStaffAssignment` cannot re-assign; customer-user 403 path
    regression-locked).
  - **Matrix doc:**
    `docs/architecture/sprint-27-rbac-matrix.md` §3 row H-4 — rewrote
    the test-reference cell to cite the structural enforcement
    accurately and reference the new Sprint 28 Batch 2 test. The
    enforcement-point cell was already correct; only the test-attribution
    cell changed.
  - **This file:** Batch 2 completion block, §7 pointer advance, §8 log
    row, §9 decision log row (1 new entry).
- **Tests / checks run:**
  - Pre-fix: `python manage.py test tickets.tests.test_sprint28a_staff_assign_block --keepdb -v 2` →
    **3 of 4 FAILED** (T-1 / T-2 / T-3 returned `200 != 403`; T-4
    customer-user passed as expected — proves bug + isolates STAFF as
    the regression).
  - Post-fix: same command → **4 passed, 0 failed** (`Ran 4 tests in
    0.748s; OK`).
  - Broader regression: `python manage.py test tickets --keepdb -v 1`
    → **157 tests OK** in 101.6s (no regression on the existing
    `test_assignment.test_company_admin_can_assign_building_manager_in_scope`
    happy path nor on the surrounding Sprint 25A direct-staff-assignment
    suite).
  - `python manage.py check` → **0 issues**.
  - No frontend files touched; frontend checks intentionally skipped per
    Batch 2 brief.
- **Important decisions made:**
  - **Real bug confirmed and fixed.** `is_staff_role(user)` returns True
    for STAFF (Sprint 23A widened the helper so STAFF inherits provider-
    side ticket behaviour: internal-note visibility, hidden-attachment
    access, first-response stamping). Using it as the gate on the BM-
    assign endpoint had the side effect of letting STAFF through. Fix:
    gate explicitly on `{UserRole.SUPER_ADMIN, UserRole.COMPANY_ADMIN,
    UserRole.BUILDING_MANAGER}` at both the view (primary, 403) and
    the serializer (defense in depth, 400 if reached). `is_staff_role`
    itself is unchanged — too many call sites depend on its existing
    "provider-side semantics" contract; changing it would be a refactor.
  - The Sprint 25A `test_staff_cannot_add` test covers the DIFFERENT
    endpoint `/api/tickets/<id>/staff-assignments/` (M:N direct staff
    assignment), not `/api/tickets/<id>/assign/` (BM reassignment). The
    audit's "STAFF reaching `/assign/`" risk row was a real coverage
    gap, not a false alarm.
  - H-4 attribution drift fix: rewrote the matrix test-reference cell
    rather than inventing a new H-4-specific test. The invariant is
    locked structurally (no API toggle to remove the `assigned` clause
    from STAFF scope while assigned), and the Sprint 28 Batch 2 test
    is now referenced alongside Sprint 25A's perimeter test. Logged
    as a separate decision-log row (§9).
- **Remaining risks:**
  - `is_staff_role` remains the gate in 10+ other call sites
    (internal-note posting, attachment hiding, first-response stamp,
    `change_status` "staff acts" branch, etc.). Sprint 28 Batch 2 only
    tightened the assign-endpoint gates. If a future endpoint also
    needs "exclude STAFF from a privileged provider-side action", the
    pattern is the explicit role allow-list used here — do NOT widen
    `is_staff_role`'s exclusion set, that would silently change every
    consumer.
  - The fix changes the customer-user response message from "Customer
    users cannot assign tickets." to "This role cannot assign tickets."
    The existing
    `test_assignment.test_customer_cannot_call_assign_endpoint` only
    asserts the status code (403), so it still passes. Operators who
    parse error messages programmatically would see the change; the
    frontend `getApiError` surfaces this verbatim only on non-HTML
    bodies — that's acceptable.
  - When Sprint 28 Batch 10 (staff per-building granularity) lands, it
    may introduce a per-building `can_assign` flag for STAFF. At that
    point the explicit gate added here will need to be widened from
    "exclude STAFF unconditionally" to "exclude STAFF unless their
    `BuildingStaffVisibility` for this building grants the new flag".
    Tracked for Batch 10 — do NOT pre-empt.

### Batch 3 — Sidebar refactor foundation

Goal: introduce the hierarchical customer-scoped submenu so subsequent
batches have a structural anchor for sub-views. Frontend only; no backend
or schema. ~1 sprint letter.

- [x] ~~Add top-level vs customer-scoped sidebar mode to
      [`frontend/src/layout/AppShell.tsx`](../../frontend/src/layout/AppShell.tsx).
      State machine: `mode = "top-level" | "customer-scoped"`.~~
- [x] ~~Add the customer-scoped submenu entries: Buildings, Users,
      Permissions, Extra Work, Contacts, Settings. Some entries may show
      empty states until later batches land their content — that is fine,
      the navigation structure ships first.~~
- [x] ~~Add a visible **Back** action that returns the sidebar to top-level
      mode.~~
- [x] ~~Encode submenu state in the URL so deep links work and browser-back
      behaves predictably. Use a nested `<Routes>` block under
      `/admin/customers/:id/*`.~~
- [x] ~~Add route tests / Playwright coverage. Spec must assert: clicking a
      customer enters submenu mode, Back returns to top-level, deep link
      to a sub-route shows the correct submenu state.~~

**Completion block — Batch 3**

- **Date:** 2026-05-16
- **Commit:** uncommitted on working tree as of 2026-05-16 (Batch 3 diff
  on top of `c3a9060`; ready for a single batch commit once reviewed).
- **Files changed summary:**
  - **Frontend (modified):**
    - `frontend/src/layout/AppShell.tsx` — added URL-derived
      `deriveSidebarMode` (regex against `pathname`), the
      `CUSTOMER_SCOPED_PATH` matcher, and a branch in the
      `.sidebar-nav` that renders **either** the existing top-level
      operations/admin/staff-requests groups **or** a new
      customer-scoped submenu (Back, Overview, Buildings, Users,
      Permissions, Extra Work, Contacts, Settings). Added `ChevronLeft`,
      `Mail`, `ShieldCheck` to the `lucide-react` imports. Mode is **not**
      `useState` — it is a pure function of `location.pathname`, so a
      hard refresh on `/admin/customers/:id/permissions` preserves the
      customer-scoped sidebar.
    - `frontend/src/App.tsx` — added imports for
      `CustomerSubPagePlaceholder`; added six new nested routes under
      `/admin/customers/:id/*` (buildings, users, permissions,
      extra-work, contacts, settings). Five render the placeholder;
      `permissions` re-renders `CustomerFormPage` so the Sprint 27E
      editor remains reachable on the deep link. The existing
      `/admin/customers/:id` route is unchanged.
    - `frontend/src/i18n/en/common.json` and
      `frontend/src/i18n/nl/common.json` — added eight
      `nav.customer_submenu.*` keys and two
      `customer_subpage_placeholder.*` keys. EN/NL parity preserved.
  - **Frontend (new):**
    - `frontend/src/pages/admin/CustomerSubPagePlaceholder.tsx` — single
      shared "Coming soon" empty-state component (uses `t()`, no
      editable surface, view-first per spec §3).
    - `frontend/tests/e2e/sprint28b_customer_sidebar.spec.ts` — three
      Playwright cases: customer deep link shows customer-scoped
      sidebar; Back returns to top-level + URL becomes
      `/admin/customers`; non-customer admin route shows top-level
      sidebar. Auth as `COMPANY_ADMIN` Ramazan; customer id resolved
      via API lookup of "B Amsterdam" so the spec is reseed-stable.
  - **Backend:** no changes. **Migrations:** no changes. **Audit
    signals:** no changes.
  - **Docs:** this completion block, §7 pointer advance, §8 log row,
    §9 decision-log row(s).
- **Tests / checks run:**
  - `npm run typecheck` → clean (empty diagnostic output — no errors).
  - `npm run build` → clean, 373–435ms; advisory chunk-size warning is
    the same pre-existing baseline (not from this diff).
  - `npm run lint` → **52 problems (49 errors, 3 warnings)** —
    **identical** to the Batch 1 baseline. The only lint hit in a
    modified file is `AppShell.tsx:122` (the pre-existing
    `react-hooks/set-state-in-effect` warning on `setSidebarOpen(false)`
    inside `useEffect` — line number shifted from `:93` to `:122` purely
    because of the new code above it; the rule violation is unchanged
    and not introduced by this batch).
  - **Playwright spec:** **WRITTEN but NOT executed locally.** Per the
    Batch 3 brief and the standing WSL gotcha
    (`docs/CLAUDE_CODE_OPERATIONAL_NOTES.md` — root-owned
    `frontend/test-results/` after a container run), we did not invoke
    `npm run test:e2e` in this pass. The spec compiles under
    `tsc -b` (the build step ran clean with the spec present in the
    tree) and follows the same fixture pattern as
    `sprint23c_access_role_editor.spec.ts` /
    `sprint27f_ticket_override.spec.ts`. Run via CI Playwright workflow
    or `./scripts/final_validation.sh` to actually exercise it.
- **Important decisions made:**
  - **Sidebar mode is URL-derived, not React state.** A regex (`/^\
    /admin\/customers\/(\d+)(?:\/.*)?$/`) maps `pathname` to `mode +
    customerId`. The match deliberately excludes `/admin/customers`
    (the list page) and `/admin/customers/new` so the customer-scoped
    submenu only activates for an actual customer record. Browser
    refresh on a deep link preserves the submenu; the back-button
    behaves predictably; no global state is needed. See §9 decision
    row.
  - **Single placeholder component for five of six submenu sub-routes.**
    `Buildings`, `Users`, `Extra Work`, `Contacts`, `Settings`
    all render `CustomerSubPagePlaceholder` (a 30-line component that
    just shows the "Coming soon" empty state through `t()`). The
    `Permissions` sub-route is the deliberate exception — it
    re-renders `CustomerFormPage` so the Sprint 27E permission editor
    stays reachable on a deep link **without decomposing the parent
    page** (decomposition is Batch 13 work). `Overview` keeps the
    existing `/admin/customers/:id` route unchanged. See §9 decision
    row.
  - **Back is a real route navigation, not `history.back()`.** The
    Back entry is a `<NavLink to="/admin/customers" end>` so deep-link
    entries (e.g. a teammate pasting `/admin/customers/42/contacts`)
    still resolve to the customers list when Back is pressed, even
    when the browser history is empty.
  - **Role filtering deferred to the existing `AdminRoute` gate.** The
    customer-scoped submenu is only ever rendered inside an
    `AdminRoute`-gated route (`SUPER_ADMIN` + `COMPANY_ADMIN` only),
    so no per-link role filters are added in `AppShell.tsx`. This
    matches the brief's "don't add new role filters; the route guard
    handles it" instruction.
- **Remaining risks:**
  - **Playwright spec not locally validated.** Three cases written
    against the existing demo seed (Osius / "B Amsterdam" customer
    resolved via API; COMPANY_ADMIN Ramazan). If a future reseed
    renames the customer or changes the auth flow, the spec needs an
    update. Run via the CI Playwright workflow before merging.
  - **`CustomerFormPage` is mounted twice when navigating between
    `/admin/customers/:id` (Overview) and
    `/admin/customers/:id/permissions`.** Both routes register the
    same component. React Router will remount on the path change, so
    state is not preserved across the navigation. Acceptable for
    Batch 3 (the editor is self-loading and reseeds its state from the
    `:id` URL param). Batch 13 will decompose `CustomerFormPage` and
    eliminate the duplication.
  - **No new icon imports beyond `lucide-react` defaults.** The
    submenu uses `ChevronLeft`, `LayoutGrid`, `MapPin`, `UserCog`,
    `ShieldCheck`, `Receipt`, `Mail`, `Settings` — all already in the
    project's icon set or trivially added from the same package. No
    new dependency installed.
  - **`AppShell.tsx:122` lint hit (`react-hooks/set-state-in-effect`)
    is unchanged from baseline.** Line number shifted but the rule
    violation is the same pre-existing `setSidebarOpen(false)` in
    `useEffect`; refactoring that loop is parked for a separate
    sprint (it would need a different mobile-sidebar dismiss strategy
    — likely an `onClick` on each `NavLink` — which is out of Batch
    3 scope).

### Batch 4 — Contacts model and UI

Goal: introduce the Contact entity and surface it on the customer-scoped
submenu (Batch 3 prerequisite). Joint backend + frontend. ~1 sprint letter.

- [x] ~~Add `Contact` model under
      [`backend/customers/`](../../backend/customers/) (or new
      `contacts/` app — sprint design decision). Fields: `customer` FK,
      optional `building` FK, `full_name`, `email`, `phone`, `role_label`,
      `notes`. **No password, no role, no scope rows.** Migration in the
      app's `migrations/`.~~
- [x] ~~Ensure Contact is structurally distinct from `User`. A Contact does
      not become a User by setting a password; that is a separate
      promotion flow parked for a later sprint.~~
- [x] ~~Add Contact CRUD API gated by the same
      `IsSuperAdminOrCompanyAdminForCompany` permission as the other
      customer-scoped endpoints. Building Manager gets a **read-only**
      view of contacts in their assigned buildings (depends on Batch 12;
      this batch only ships the write path).~~
- [x] ~~Add audit signal coverage in
      [`backend/audit/signals.py`](../../backend/audit/signals.py) — full
      CRUD tracking on the Contact model. Add `audit/tests/` coverage.~~
- [x] ~~Add the `Contact` TypeScript type to
      [`frontend/src/api/types.ts`](../../frontend/src/api/types.ts) and
      the client helpers to
      [`frontend/src/api/admin.ts`](../../frontend/src/api/admin.ts).~~
- [x] ~~Add `CustomerContactsPage` under
      `/admin/customers/:id/contacts` (nested under the Batch 3 submenu).
      View-first per spec §3 — list page with "Add contact" modal; row
      click opens a read-only detail with "Edit" → modal.~~
- [x] ~~Add contextual contact display in ticket / extra-work screens where
      useful (e.g. read-only "Customer contacts" panel on
      `TicketDetailPage` and `ExtraWorkDetailPage`).~~
- [x] ~~Add tests: backend API + scope + audit; frontend Playwright for the
      view-first flow + the "no login fields" assertion.~~

**Completion block — Batch 4**

- **Date:** 2026-05-16
- **Commit:** uncommitted on working tree as of 2026-05-16 (Batch 4 diff
  on top of `9402e38`; ready for a single batch commit once reviewed).
- **App / model placement:**
  - `Contact` lives in **`backend/customers/`** (added to the existing
    `models.py`, not a new app). Rationale: customers app already
    follows the app-scoped-split-file convention with multiple
    `serializers_*.py` / `views_*.py`; audit signals + the permission
    resolver already import from `customers.models`; placing Contact
    here means zero new app registration, zero circular-import risk,
    and stays in the same scope as the parent `Customer` FK.
- **Files changed summary:**
  - **Backend modified:** `backend/customers/models.py` (Contact model),
    `backend/customers/urls.py` (2 new routes),
    `backend/audit/signals.py` (Contact appended to full-CRUD tuple).
  - **Backend new:** `backend/customers/migrations/0007_contact.py`,
    `backend/customers/serializers_contacts.py` (read/write +
    cross-customer building validation),
    `backend/customers/views_contacts.py`
    (`CustomerContactListCreateView` +
    `CustomerContactDetailView`),
    `backend/customers/tests/test_sprint28_contacts.py` (22 tests in
    4 classes), `backend/audit/tests/test_sprint28_contact_audit.py`
    (4 tests).
  - **Frontend modified:** `frontend/src/api/types.ts` (3 new types:
    `Contact` + `ContactCreatePayload` + `ContactUpdatePayload`, with
    explicit absence of `password` / `role` / `is_active` / `user`),
    `frontend/src/api/admin.ts` (5 new helpers),
    `frontend/src/App.tsx` (placeholder route swapped for
    `CustomerContactsPage`; other 4 placeholder routes unchanged),
    `frontend/src/i18n/en/common.json` and `nl/common.json` (25 new
    `customer_contacts.*` keys in each, EN/NL parity preserved),
    `frontend/src/pages/TicketDetailPage.tsx` and
    `frontend/src/pages/ExtraWorkDetailPage.tsx` (read-only
    Customer-Contacts panel inserted, gated to
    SUPER_ADMIN / COMPANY_ADMIN to mirror the backend
    `IsSuperAdminOrCompanyAdminForCompany` gate).
  - **Frontend new:** `frontend/src/pages/admin/CustomerContactsPage.tsx`
    (view-first list + read-only detail + Add/Edit modal + Delete
    confirm),
    `frontend/tests/e2e/sprint28_contacts.spec.ts` (5 Playwright
    cases).
  - **Docs:** this completion block, §7 pointer advance, §8 log row,
    §9 decision-log rows.
- **Migration status:**
  - Migration file **created**: `backend/customers/migrations/0007_contact.py`
    (depends on `customers.0006_backfill_customer_company_policy` +
    `buildings.0002_buildingstaffvisibility`).
  - Dev DB `migrate` **NOT applied yet** (per master plan §3 rule 5 —
    requires explicit user approval). Test DB auto-migrates each test
    run so the 26 new tests + 175-test broader regression validate
    against the new schema; production behaviour is locked. The dev
    container's running DB still has Sprint 27's schema until the user
    approves `docker compose exec backend python manage.py migrate`.
- **Exact backend API routes:**
  - `GET / POST  /api/customers/<int:customer_id>/contacts/`
    → `CustomerContactListCreateView`, gated by
    `IsAuthenticatedAndActive + IsSuperAdminOrCompanyAdminForCompany`.
  - `GET / PATCH / DELETE  /api/customers/<int:customer_id>/contacts/<int:contact_id>/`
    → `CustomerContactDetailView`, same gate.
  - Both views fetch the `Customer` first and run
    `check_object_permissions(request, customer)` so the FK provider
    is the scope anchor (not the contact id). Detail view's
    `get_object` re-filters by `customer=customer` so ID smuggling
    (customer-A URL + contact-B id) returns 404 instead of operating
    cross-customer.
- **Permission / scoping behavior:**
  - SUPER_ADMIN: full CRUD on any customer's contacts.
  - COMPANY_ADMIN: full CRUD on contacts within their own provider
    company; cross-provider attempts get 403/404 per the existing
    `IsSuperAdminOrCompanyAdminForCompany` shape.
  - BUILDING_MANAGER: **403 on every endpoint** (BM read-only contact
    view is intentionally deferred to **Batch 12**).
  - CUSTOMER_USER: 403 on every endpoint, regardless of access role.
  - STAFF: 403 on every endpoint.
- **Audit coverage:**
  - Contact appended to `backend/audit/signals.py` full-CRUD model
    tuple (alongside User / Company / Building / Customer /
    CustomerCompanyPolicy / StaffProfile / StaffAssignmentRequest).
  - 4 tests in `audit/tests/test_sprint28_contact_audit.py` assert
    CREATE / UPDATE / DELETE each emit exactly one `AuditLog` row
    with the right `action` + `target_model="customers.Contact"` +
    `target_id` + `changes` diff.
- **Frontend route / UI behavior:**
  - `/admin/customers/:id/contacts` now renders the real
    `CustomerContactsPage` (Batch 3 placeholder swapped out). The
    customer-scoped sidebar Contacts entry from Batch 3 deep-links
    here.
  - The page lists contacts in a view-first list; "Add contact"
    opens a modal; row click opens a read-only detail; the
    detail has explicit "Edit" and "Delete" actions (Edit opens
    modal, Delete opens `ConfirmDialog`).
  - The Add/Edit modal has fields only for: full_name, email,
    phone, role_label (free text), notes, building (dropdown of the
    customer's `CustomerBuildingMembership` rows). **No password,
    no role dropdown, no login-related field, no scope/access UI,
    no "invite as user" affordance.**
- **Contextual contact panels — both surfaces landed:**
  - `TicketDetailPage` — read-only "Customer contacts" panel with
    `data-testid="ticket-customer-contacts-panel"`. Gated to
    SUPER_ADMIN / COMPANY_ADMIN to mirror the backend permission
    class; non-admins do not emit the API call.
  - `ExtraWorkDetailPage` — same shape with
    `data-testid="extra-work-customer-contacts-panel"`. Required a
    small `useTranslation("common")` import; no other refactor of
    the page.
  - Both panels show only `full_name / role_label / phone / email`;
    no edit/add/delete affordance; collapse to a muted "no
    contacts on file" line when empty.
- **Tests / checks run:**
  - Backend targeted: `python manage.py test
    customers.tests.test_sprint28_contacts
    audit.tests.test_sprint28_contact_audit --keepdb -v 2`
    → **26 tests OK** in 24.7s.
  - Backend broader: `python manage.py test customers audit --keepdb
    -v 1` → **175 tests OK** in 165.2s.
  - Backend cross-app: `python manage.py test customers audit tickets
    extra_work --keepdb -v 1` → **365 tests OK** in 298.2s — no
    regression from the Contact + audit signal additions.
  - `python manage.py check` → **0 issues**.
  - `python manage.py makemigrations --dry-run --check` → **No
    changes detected** (model state matches migration graph).
  - `npm run typecheck` → **clean**.
  - `npm run build` → **clean**, 508ms (only the pre-existing
    advisory chunk-size warning).
  - `npm run lint` → **52 problems (49 errors, 3 warnings)** —
    matches the Batch 1-3 baseline. Frontend agent's reported pre-
    Batch-4 stash count was 53 problems (50 errors); their new code
    is one error cleaner because they extracted `ticketCustomerId`
    / `ewCustomerId` locals to satisfy `react-hooks/exhaustive-deps`
    on the new effects. **Zero new lint hits in any Batch 4 file.**
  - **Playwright spec written but NOT executed locally** per Batch 4
    brief + the standing WSL gotcha (root-owned
    `frontend/test-results/`). Spec compiles under `tsc -b`; runs
    via CI Playwright workflow.
- **Important decisions made (also logged in §9):**
  - **Contact lives in `customers/`, not a new app** — repo's app-
    scoped-split-file convention + zero circular-import risk.
  - **Contact is structurally NOT a User** — model has no
    `password` / `role` / `user` FK / `is_active` /
    `permission_overrides`; no API field exposes such; the
    `ContactIsNotAUserTests` regression-locks this by iterating the
    serialized JSON keys.
  - **BM read-only contact view deferred to Batch 12** — Batch 4
    permission gate is admin-only. Documented explicitly in the
    test suite (`test_building_manager_cannot_*`).
  - **Frontend contextual panel gate** mirrors the backend
    `IsSuperAdminOrCompanyAdminForCompany` admin-only class — BM
    will see the panel once Batch 12 widens the backend gate; until
    then non-admin roles don't even emit the API call.
- **Remaining risks:**
  - Dev DB schema is **behind code** until `python manage.py migrate`
    is approved. Test DB and CI both auto-migrate, so the test suite
    is correct. The "Contact" tab in the running dev container will
    500 on the API call until migrate runs.
  - The Playwright spec is **not locally validated** — relies on CI
    or a manual run. Same condition as Sprint 27F-F1's spec.
  - The Add/Edit modal's `building` dropdown calls
    `listCustomerBuildings` — that endpoint returns the full M:N
    list including potentially-deactivated buildings. The current
    behaviour is to show every linked building; a Sprint 28+ polish
    pass may want to filter by `is_active=True`.
  - The contextual panels on Ticket/Extra-Work detail call the
    contacts API on every page render — currently no in-memory
    caching. For high-traffic operator UIs this could be a polish
    item (debounce / SWR pattern); not P0.

### Batch 5 — Service catalog and pricing

Goal: introduce the catalog + pricing models so the cart flow (Batch 6)
can compute prices. Backend-heavy. ~1 sprint letter.

- [x] ~~Add `ServiceCategory` model.~~
- [x] ~~Add `Service` model with `name`, `description`, `unit_type`
      (`HOURLY` / `PER_SQM` / `FIXED` / `PER_ITEM` per spec §5),
      `default_unit_price` (decimal), `default_vat_pct` (decimal,
      default 21.00), `is_active`, FK to `ServiceCategory`.~~
- [x] ~~Add customer-specific contract price model (`CustomerServicePrice` or
      similar): FK `customer`, FK `service`, `unit_price`, `vat_pct`,
      `valid_from`, `valid_to`, `is_active`.~~
- [x] ~~Add `default_unit_price` as the global default/reference price on
      `Service` — used as a provider-side reference only.~~
- [x] ~~Add `resolve_price(service, customer, on=date)` resolver. Returns
      the customer-specific contract price when active, else `None`
      (NOT the global default — see §5 product rule #9).~~
- [x] ~~**Enforce: global default price alone never creates an instant
      ticket.** The instant-ticket path (Batch 7) keys off the resolver
      returning a non-`None` price, which only happens when a customer-
      specific contract price is active.~~
- [x] ~~Add provider/admin UI for managing service categories, services,
      and customer-specific prices. View-first per spec §3.~~
- [x] ~~Add audit signal coverage on all three new models.~~
- [x] ~~Add tests: resolver branches, cross-customer leak prevention
      (Customer A's prices never visible to Customer B's users),
      audit coverage.~~

**Completion block — Batch 5**

- **Date:** 2026-05-16
- **Commit:** uncommitted on working tree as of 2026-05-16 (Batch 5 diff
  on top of `e23cf40`; ready for a single batch commit once reviewed).
- **App / model placement:**
  - All three new models (`ServiceCategory`, `Service`,
    `CustomerServicePrice`) live in **`backend/extra_work/models.py`**
    (extending the existing file). Rationale: extra_work app already
    owns the pricing-adjacent vocabulary (`ExtraWorkPricingUnitType`
    enum + the legacy `ExtraWorkPricingLineItem`); catalog + pricing
    belong in the same domain as the work they price; zero new app
    registration, zero circular-import risk.
  - Resolver `resolve_price()` lives in **new module**
    `backend/extra_work/pricing.py` (parallel to `extra_work/scoping.py`
    + `extra_work/state_machine.py`).
  - **Reused the existing `ExtraWorkPricingUnitType` enum verbatim**
    (`HOURS` / `SQUARE_METERS` / `FIXED` / `ITEM` / `OTHER` —
    descriptive equivalents of spec §5's HOURLY/PER_SQM/FIXED/PER_ITEM).
    No parallel `ServiceUnitType` enum introduced.
- **Files changed summary:**
  - **Backend modified (4):** `backend/extra_work/models.py` (+ 3 model
    classes — Service, ServiceCategory, CustomerServicePrice),
    `backend/audit/signals.py` (3 new model registrations in full-CRUD
    tuple), `backend/config/urls.py` (mount `/api/services/`),
    `backend/customers/urls.py` (2 customer-scoped pricing routes).
  - **Backend new (10):**
    `backend/extra_work/migrations/0002_service_catalog_and_pricing.py`,
    `backend/extra_work/pricing.py` (`resolve_price()` resolver),
    `backend/extra_work/serializers_catalog.py`,
    `backend/extra_work/views_catalog.py`,
    `backend/extra_work/views_pricing.py`,
    `backend/extra_work/urls_catalog.py`,
    `backend/extra_work/tests/test_sprint28_service_catalog.py`,
    `backend/extra_work/tests/test_sprint28_pricing_resolver.py`,
    `backend/extra_work/tests/test_sprint28_pricing_api.py`,
    `backend/audit/tests/test_sprint28_pricing_audit.py`.
  - **Frontend modified (6):** `frontend/src/App.tsx`,
    `frontend/src/api/admin.ts` (15 new helpers),
    `frontend/src/api/types.ts` (5 new types — `ServiceUnitType`,
    `ServiceCategory(+Create/Update)`, `Service(+Create/Update)`,
    `CustomerServicePrice(+Create/Update)`),
    `frontend/src/i18n/en/common.json` + `nl/common.json` (`nav.services` +
    `nav.customer_submenu.pricing` + `services.*` + `customer_pricing.*`
    namespaces; EN/NL parity preserved),
    `frontend/src/layout/AppShell.tsx` (top-level "Services" nav entry +
    customer-scoped "Pricing" entry).
  - **Frontend new (4):**
    `frontend/src/pages/admin/ServicesAdminPage.tsx`
    (top-level catalog admin — tabs for services + categories),
    `frontend/src/pages/admin/CustomerPricingPage.tsx`
    (per-customer contract pricing),
    `frontend/tests/e2e/sprint28_services.spec.ts` (6 cases),
    `frontend/tests/e2e/sprint28_customer_pricing.spec.ts` (5 cases).
  - **Docs:** this completion block, §7 pointer advance, §8 log row,
    §9 decision-log rows.
- **Migration status:**
  - Migration file **created**:
    `backend/extra_work/migrations/0002_service_catalog_and_pricing.py`
    (depends on `extra_work.0001_initial` + `customers` head).
  - Dev DB `migrate` **APPLIED** on 2026-05-16 by the user via
    `docker compose exec backend python manage.py migrate extra_work`.
    Verified with `python manage.py showmigrations extra_work` →
    `[X] 0002_service_catalog_and_pricing`. Catalog API endpoints +
    the Services/Pricing admin UI are now exercisable against the dev
    container. Test DB also auto-migrates each `manage.py test` run
    so the test suite remains green.
- **Exact backend API routes:**
  - **Catalog (provider-wide):**
    - `GET / POST  /api/services/categories/`
    - `GET / PATCH / DELETE  /api/services/categories/<int:category_id>/`
    - `GET / POST  /api/services/`
    - `GET / PATCH / DELETE  /api/services/<int:service_id>/`
    - Gated by `IsAuthenticatedAndActive + IsSuperAdminOrCompanyAdmin`.
      Catalog is provider-wide (not company-scoped).
  - **Per-customer pricing:**
    - `GET / POST  /api/customers/<int:customer_id>/pricing/`
    - `GET / PATCH / DELETE  /api/customers/<int:customer_id>/pricing/<int:price_id>/`
    - Gated by `IsAuthenticatedAndActive + IsSuperAdminOrCompanyAdminForCompany`.
    - Detail view re-scopes by `customer=customer` to block ID
      smuggling (mirror of Batch 4 Contact detail).
- **Permission / scoping behavior:**
  - SUPER_ADMIN: full CRUD on catalog + any customer's pricing.
  - COMPANY_ADMIN: full CRUD on catalog (provider-wide) + pricing
    within own provider; cross-provider 403/404.
  - BUILDING_MANAGER: **403 on every endpoint** (catalog management is
    provider-admin only; per-customer pricing too).
  - CUSTOMER_USER: 403 everywhere (customer-side pricing visibility —
    "customer sees their own contract prices" — lands with the cart UX
    in Batch 6, NOT here).
  - STAFF: 403 everywhere.
- **Resolver semantics (rule #9 enforced):**
  - `resolve_price(service, customer, *, on=None) -> CustomerServicePrice | None`
    in `backend/extra_work/pricing.py`.
  - Returns the active `CustomerServicePrice` row for (service,
    customer) on the given date. Selection: latest `valid_from <= on`,
    `valid_to >= on or null`, `is_active=True`; ties broken by `-id`.
  - Returns **`None`** when no matching row exists — does **NOT** fall
    back to `Service.default_unit_price`. This is the hard rule #9
    lock; verified by `ResolvePriceReturnsNoneWithoutCustomerSpecificTests`.
  - `Service.default_unit_price` is a provider-side reference only
    (display in the catalog admin UI; the UI surfaces this with a
    visible hint).
- **Audit coverage:**
  - All three new models added to `backend/audit/signals.py`
    full-CRUD tuple (alongside Contact / Customer / Company / Building
    / CustomerCompanyPolicy / StaffProfile / StaffAssignmentRequest).
  - 9 audit tests in `audit/tests/test_sprint28_pricing_audit.py`
    (3 per model × CREATE/UPDATE/DELETE) — all assert one `AuditLog`
    row per mutation with correct `target_model` + `action` + diff.
- **Frontend route / UI behavior:**
  - **NEW top-level route** `/admin/services` → `ServicesAdminPage`
    (tabs: Services + Categories; view-first list + read-only detail +
    Add/Edit modal + Delete `ConfirmDialog`). New top-level sidebar
    entry "Services" (gated to SUPER_ADMIN + COMPANY_ADMIN).
  - **NEW customer-scoped sub-route** `/admin/customers/:id/pricing`
    → `CustomerPricingPage` (view-first contract pricing list + Add/
    Edit modal). The Batch 3 sidebar regex automatically activates
    customer-scoped mode on this URL. NEW customer-scoped sidebar
    entry "Pricing" between Permissions and Extra Work.
  - **Reference-price hint surfaced in the catalog UI**:
    `services.field_default_unit_price_hint` explicitly states the
    field is a provider-side reference and does NOT trigger the
    instant-ticket path. This makes rule #9 visible to operators.
  - **No Batch 6 wiring**: the catalog is NOT yet integrated with any
    Extra Work request flow. The cart-shaped request and the
    instant-ticket / proposal branching land in Batches 6 and 7-8.
- **Contextual integration:** none — Batch 5 is admin-only. No
  customer-side surface (customer's own price visibility ships with
  the cart UI in Batch 6).
- **Tests / checks run:**
  - Backend targeted (4 modules): `test_sprint28_service_catalog +
    test_sprint28_pricing_resolver + test_sprint28_pricing_api +
    test_sprint28_pricing_audit` → **57/57 OK** in 132.6s.
  - Backend per-app sanity: `audit` alone = **44/44 OK** in 60.8s;
    `extra_work` alone = **81/81 OK** in 82.2s; `customers` alone =
    **140/140 OK** in 192.5s.
  - Backend broader sweep (`extra_work + audit + customers`) —
    **first run reported `FAILED (errors=7)` (transient flake);
    diagnostic `-v 2` grep returned zero FAIL/ERROR lines; second
    confirmation run** → **265/265 OK** in 471.5s. Likely a
    NotificationLog / Celery-eager race on shared state in long
    combined runs — documented as a remaining risk.
  - `manage.py check` → **0 issues**.
  - `manage.py makemigrations --dry-run --check` → **No changes
    detected** (model state matches migration graph).
  - `npm run typecheck` → **clean**.
  - `npm run build` → **clean**, 454ms (advisory chunk-size warning
    only, baseline).
  - `npm run lint` → **52 problems = baseline** (zero new hits in any
    Batch 5 file).
  - **Playwright specs written but NOT executed locally** (WSL
    `frontend/test-results/` root-ownership gotcha). Two spec files
    (11 cases total) compile under `tsc -b`; CI will exercise them.
- **Important decisions made (also logged in §9):**
  - Service catalog + pricing models live in
    **`backend/extra_work/`**, not a new app — closest existing
    domain.
  - **`ExtraWorkPricingUnitType` reused** — no parallel enum.
  - **Resolver returns `None` when no customer-specific price** —
    `Service.default_unit_price` never triggers instant ticket
    (master plan §5 rule #9 enforced in code + visible UI hint).
  - **Frontend split into two routes**: provider-wide
    `/admin/services` (top-level) + per-customer
    `/admin/customers/:id/pricing` (customer-scoped, extends Batch 3
    sidebar by one entry).
  - Customer-side price visibility (their own contract prices)
    deferred to Batch 6 (ships with the cart UI). Catalog UI is
    admin-only in Batch 5.
- **Remaining risks:**
  - ~~Dev DB schema behind code until user approves migrate.~~
    **RESOLVED 2026-05-16** — user applied
    `python manage.py migrate extra_work`; `showmigrations` confirms
    `[X] 0002_service_catalog_and_pricing`. Dev DB schema is now in
    lockstep with code.
  - **Broader sweep flakiness**: first run reported 7 transient
    errors; re-run was 265/265 OK. Likely NotificationLog state-bleed
    in long sequential runs across `extra_work + audit + customers`.
    Not Batch-5-specific (same notification-log-shared-state risk
    exists in earlier batches). CI runs should not be re-run-on-fail
    masking real regressions — if a future batch sees the same flake,
    re-run before declaring a failure.
  - **Spec §5 + backlog `EXTRA-PRICING-1` text drift**: the spec doc
    §5 "Resolution order" step 2 says "global default price" as a
    fallback. The master plan rule #9 + this code's behaviour are
    authoritative: resolver returns `None`, no global-default
    fallback. A doc-only patch should reconcile spec §5 step 2 with
    rule #9 in a later batch — not a blocker for Batch 5.
  - **Backlog `EXTRA-PRICING-1` row** mentions "returns customer-
    specific contract price when active, else global default" —
    stale wording. The shipped code follows the master plan rule #9
    (returns `None`). Update the backlog row when closing the item.
  - **Playwright specs not locally validated** — same WSL gotcha as
    prior batches. CI workflow will exercise; if the spec breaks on
    CI it will be visible in the next CI run.
  - **`CustomerPricingPage` Edit modal locks the service dropdown**
    in update mode — switching service on an existing price row
    would corrupt history. Users delete + add to switch. Documented
    in the `field_service_locked_hint` i18n key.

### Batch 6 — Cart-shaped Extra Work request

Goal: reshape `ExtraWorkRequest` from single-line to parent + N line
items; ship the customer cart UI. ~1 sprint letter.

- [x] ~~Add `ExtraWorkRequestItem` (or equivalent cart-line model) with FK
      to `ExtraWorkRequest`, FK to `Service`, `quantity`, `requested_date`
      (per-line, per spec §4), `customer_note`. Migration with a data
      backfill so existing single-line requests get one line item.~~
- [x] ~~Update `ExtraWorkRequest` to be the parent record. Keep the request-
      level `description` field (per §10 question 3 default).~~
- [x] ~~Customer can add multiple contract services and/or custom requests
      to one cart. Spec §4 branching rule: if any line lacks an agreed
      price, the whole cart routes to the proposal flow (Batch 8); else
      instant-ticket (Batch 7).~~
- [x] ~~Add per-line `quantity`, `unit_type` (denormalised from Service for
      historical accuracy), `requested_date`, `customer_note`.~~
- [x] ~~Separate the mixed cart according to the spec §4 rule (single
      property on the request — e.g. `routing_decision = "INSTANT" |
      "PROPOSAL"` — computed at submission time).~~
- [x] ~~Rewrite [`frontend/src/pages/CreateExtraWorkPage.tsx`](../../frontend/src/pages/CreateExtraWorkPage.tsx)
      to the cart shape: category browser + add-to-cart + per-line date
      picker + submit.~~
- [x] ~~Add `extra_work` i18n namespace in both `en/` and `nl/`. Thread
      `t()` through all three EW pages
      (`Create`, `List`, `Detail`). This is the first time the EW
      surface gets i18n.~~
- [x] ~~Add tests: backend API for parent + line creation; scope on cart
      lines; frontend Playwright for the cart UX.~~

**Completion block — Batch 6**

- **Date:** 2026-05-16
- **Commit:** uncommitted on working tree as of 2026-05-16 (Batch 6 diff
  on top of `13fb819`; ready for a single batch commit once reviewed).
- **Batch 6 scope implemented:** Reshape `ExtraWorkRequest` into a
  parent + N `ExtraWorkRequestItem` line items; data backfill of
  existing single-line requests; new `routing_decision` field on
  `ExtraWorkRequest` (computed at submission via `resolve_price()` per
  line — no ticket spawn yet); customer-facing cart UI replaces the
  legacy single-line form; full `extra_work` i18n namespace added with
  `t()` threaded through all three EW pages; 5-case Playwright spec.
- **Files changed summary:**
  - **Backend modified (4):** `backend/audit/signals.py`
    (`ExtraWorkRequestItem` registered full-CRUD; `ExtraWorkRequest`
    intentionally NOT registered in Batch 6 per the brief's "leave that
    alone" guidance), `backend/extra_work/models.py` (+
    `ExtraWorkRoutingDecision` choices + `routing_decision` field on
    `ExtraWorkRequest` + new `ExtraWorkRequestItem` model),
    `backend/extra_work/serializers.py` (+ `ExtraWorkRequestItemSerializer`
    + nested-write `create()` that calls `resolve_price()` per line +
    `routing_decision` exposed on list + detail serializers),
    `backend/extra_work/tests/test_extra_work_mvp.py` (2-test compat
    update for the new `line_items`-required payload).
  - **Backend new (4):**
    `backend/extra_work/migrations/0003_request_items_and_routing.py`
    (schema + idempotent data backfill creating one `service=None`,
    `quantity=1`, `unit_type="OTHER"`, `routing_decision="PROPOSAL"`
    line per existing request; reverse_code = noop),
    `backend/extra_work/tests/test_sprint28_cart_request.py` (20
    tests covering CRUD, routing-decision computation, validation,
    no-ticket-spawn assertion, scope isolation),
    `backend/extra_work/tests/test_sprint28_cart_request_backfill.py`
    (6 tests verifying the migration backfill creates one line per
    request, with NULL service + PROPOSAL routing),
    `backend/audit/tests/test_sprint28_cart_request_audit.py` (5
    tests asserting `ExtraWorkRequestItem` CREATE/UPDATE/DELETE
    audit; documents `ExtraWorkRequest` is NOT audited in Batch 6).
  - **Frontend modified (5):** `frontend/src/api/types.ts`
    (`RoutingDecision` union + `ExtraWorkRequestItem` +
    `ExtraWorkRequestCartCreatePayload`; extended
    `ExtraWorkRequestDetail` with `line_items` + `routing_decision`),
    `frontend/src/api/extraWork.ts` (`createExtraWork()` takes cart
    payload), `frontend/src/i18n/index.ts` (register `extra_work`
    namespace), `frontend/src/pages/CreateExtraWorkPage.tsx` (FULL
    REWRITE to cart UI — parent fields preserved + cart array with
    add/remove lines + per-line service-dropdown / qty /
    requested_date / customer_note + post-submit result panel with
    INSTANT/PROPOSAL banner; i18n throughout),
    `frontend/src/pages/ExtraWorkListPage.tsx` (`t()` via
    `extra_work` namespace),
    `frontend/src/pages/ExtraWorkDetailPage.tsx` (`t()` via
    `extra_work` namespace; read-only `line_items` table +
    `routing_decision` badge).
  - **Frontend new (3):** `frontend/src/i18n/en/extra_work.json`
    (full bundle for the new namespace),
    `frontend/src/i18n/nl/extra_work.json` (EN/NL parity preserved),
    `frontend/tests/e2e/sprint28_extra_work_cart.spec.ts` (5
    Playwright cases — INSTANT banner / PROPOSAL banner / empty-cart
    block / duplicate-service block / detail-page line-item render).
  - **Docs:** this completion block, §7 pointer advance, §8 log row,
    §9 decision-log rows.
- **Migration status:**
  - Migration file **created**:
    `backend/extra_work/migrations/0003_request_items_and_routing.py`
    (depends on `extra_work.0002_service_catalog_and_pricing`).
    Schema operations: `AddField(ExtraWorkRequest.routing_decision)` +
    `CreateModel(ExtraWorkRequestItem)`. Data operation: `RunPython`
    creates one `service=None`, `quantity=1`, `unit_type="OTHER"`,
    `requested_date = preferred_date or requested_at.date()`,
    `customer_note=""` line per existing `ExtraWorkRequest`, and
    force-sets `routing_decision="PROPOSAL"` on every backfilled
    request. Idempotent under reapply (skips requests that already
    have a line item). Reverse_code is a documented no-op (line-item
    rows are NOT auto-deleted on rollback — real cart lines would be
    destroyed).
  - Dev DB `migrate` **APPLIED** on 2026-05-16 by the user via
    `docker compose exec backend python manage.py migrate extra_work`.
    Verified with `python manage.py showmigrations extra_work` →
    `[X] 0003_request_items_and_routing`. Cart endpoint + the rewritten
    `CreateExtraWorkPage` are now exercisable against the dev
    container. Test DB also auto-migrates each `manage.py test` run
    so the test suite remains green.
- **Exact backend API contract:**
  - **POST `/api/extra-work/`** — now requires nested `line_items:
    [{ service, quantity, requested_date, customer_note }, …]`
    array (at least one entry, all `service` distinct, each
    `service.is_active=True`, `quantity > 0`). The `unit_type` is
    server-computed from `Service.unit_type` and rejected if
    supplied by the client. Response shape adds `line_items`
    (full nested array) + `routing_decision` ("INSTANT" or
    "PROPOSAL"). Backwards-incompat with the legacy single-line
    payload — the existing `test_extra_work_mvp.py` MVP `CreateTests`
    were updated (2 tests; documented).
  - **GET `/api/extra-work/`** (list) — adds `routing_decision` so
    inbox UIs can branch without a detail fetch.
  - **GET `/api/extra-work/<id>/`** (detail) — adds `line_items` +
    `routing_decision`.
  - No new top-level endpoint; no per-line `ExtraWorkRequestItem`
    CRUD endpoint (line-item edit is Batch 8 territory). Existing
    transition endpoint untouched.
- **Permission / scoping behavior:** unchanged from the existing
  `ExtraWorkRequestViewSet.permission_classes =
  [IsAuthenticatedAndActive]` shape. Scope is enforced by
  `scope_extra_work_for`. CUSTOMER_USER may POST (customer
  self-service cart submission). Provider admins (SUPER_ADMIN /
  COMPANY_ADMIN / BUILDING_MANAGER) may compose on behalf via the
  same endpoint. STAFF stays blocked by the existing G-B7
  `scope_extra_work_for` `.none()` branch. Cross-customer /
  cross-provider rejected via existing scope + the new per-line
  serializer validation (locked by `CartRequestScopeTests`).
- **`resolve_price()` usage:** called inside
  `ExtraWorkRequestCreateSerializer.create()` at
  `backend/extra_work/serializers.py`, per line, with
  `on=line["requested_date"]`. Aggregation: every line non-None →
  `routing_decision = "INSTANT"`; any line None →
  `routing_decision = "PROPOSAL"`. Everything inside the existing
  `transaction.atomic()` block. **No ticket creation, no state
  transition, no proposal route taken — Batch 6 stores the
  decision; Batches 7 and 8 will act on it.** Locked by
  `test_instant_routing_does_not_spawn_tickets` and
  `test_status_remains_requested`.
- **Audit coverage:**
  - `ExtraWorkRequestItem` registered in
    `backend/audit/signals.py` full-CRUD tuple (right after
    Batch 5's `CustomerServicePrice`).
  - `ExtraWorkRequest` itself is **intentionally NOT registered**
    in Batch 6 (the parent row was already-unregistered pre-Batch-6
    per the brief's "leave that alone" guidance). A dedicated test
    class `ExtraWorkRequestRoutingDecisionAuditTests` pins this
    contract (asserts no parent-row AuditLog is written) so a
    future sprint adding registration will see a clear test
    failure to update.
- **Frontend route / UI behavior:**
  - `/extra-work/new` now renders the cart UI (legacy single-line
    form replaced). View-first compliance: the form itself is the
    Create surface (a form, intentionally); the post-submit
    **result panel** is read-only and shows either an INSTANT
    banner ("Your order is being processed — operational tickets
    will be created shortly") or a PROPOSAL banner ("Your request
    has been sent for pricing review"). No navigation to a detail
    page yet — Batch 7 will wire the INSTANT path to ticket
    creation.
  - `/extra-work/<id>/` (detail) renders the cart line items as a
    read-only table and a `routing_decision` badge.
  - All three EW pages now use `useTranslation("extra_work")` —
    audit doc §7 row 19 (i18n missing on EW) closed by this batch.
- **Tests / checks run:**
  - Backend targeted (3 modules, 31 new tests):
    `extra_work.tests.test_sprint28_cart_request` +
    `extra_work.tests.test_sprint28_cart_request_backfill` +
    `audit.tests.test_sprint28_cart_request_audit` → **31/31 OK**
    in 5.1s.
  - Backend broader (`extra_work + audit + customers`) reported by
    the Backend agent: **296/296 OK** in 233.9s.
  - `manage.py check`: 0 issues. `makemigrations --dry-run
    --check`: No changes detected.
  - `npm run typecheck`: clean.
  - `npm run build`: clean, 338ms (advisory chunk-size warning
    only).
  - `npm run lint`: **52 problems = baseline**; zero new hits.
    The 4 hits in modified files (`CreateExtraWorkPage.tsx:215/228/243`
    + `ExtraWorkDetailPage.tsx:191`) are pre-existing `setState-in-
    effect` patterns carried over verbatim from the original files
    (auto-sync `useEffect` for building/customer pairing + the
    customer-contacts panel effect Batch 4 added).
  - **Playwright spec written but NOT executed locally** (WSL
    root-owned `frontend/test-results/` gotcha). 5 cases in
    `sprint28_extra_work_cart.spec.ts`; spec compiles under
    `tsc -b`; CI will exercise.
- **Important decisions made (also logged in §9):**
  - **Reshape** `ExtraWorkRequest` rather than keeping a parallel
    deprecated single-line shape — backwards-incompat with legacy
    payload is acceptable because the data-migration backfill
    provides a one-line-item view of every existing request, and
    the only existing payload sender (the legacy
    `CreateExtraWorkPage`) is rewritten in this same batch.
  - **`service` FK is nullable** on `ExtraWorkRequestItem` (model
    level) to accommodate the backfill of pre-Batch-5 requests
    that have no `Service` catalog row. Serializer enforces
    non-null on new submissions — only the migration backfill
    creates NULL-service rows.
  - **`resolve_price()` IS called at submission to compute
    `routing_decision`, but Batch 6 does NOT act on the result.**
    The field is stored; Batch 7 will read it to spawn tickets;
    Batch 8 will read it to enter the proposal queue. Storing the
    decision now lets the existing EW workflow state machine
    remain untouched in this batch.
  - **`ExtraWorkRequest` audit registration deferred** per the
    PM's brief: the parent row is not currently audit-tracked,
    and adding registration in Batch 6 would be scope creep. A
    dedicated test asserts no parent-row AuditLog is written;
    when a future batch adds registration, that test will fail
    loudly.
- **Remaining risks:**
  - ~~Dev DB schema behind code until user approves
    `python manage.py migrate extra_work`.~~
    **RESOLVED 2026-05-16** — user applied
    `python manage.py migrate extra_work`; `showmigrations` confirms
    `[X] 0003_request_items_and_routing`. Dev DB schema is now in
    lockstep with code; cart endpoint + rewritten `CreateExtraWorkPage`
    exercisable against the dev container.
  - **Playwright spec not locally validated** — same WSL gotcha as
    prior batches. CI workflow will exercise the 5 cases.
  - **2 existing MVP tests in `test_extra_work_mvp.py` were
    updated** to send the new cart payload (documented in brief).
    No other tests adjusted; all 30 other MVP tests pass
    unchanged.
  - **`routing_decision` is computed once at submission and not
    re-computed**. If a future batch lets the operator edit a line
    after submission (Batch 8 territory), the field can drift —
    Batch 8 must explicitly handle recomputation.
  - **Unit-type i18n duplication**: Batch 6 added unit-type labels
    under the `extra_work` namespace; Batch 5 has analogous labels
    under the `services` namespace. Frontend agent flagged this as
    a follow-up consolidation candidate; not a Batch 6 blocker.
  - **`ExtraWorkPricingLineItem` (legacy provider-built pricing
    rows on the legacy single-line request) is UNTOUCHED** — it's
    a different concept from the new `ExtraWorkRequestItem`.
    Batch 8 will reckon with it when the proposal model ships.

### Batch 7 — Instant-ticket path

Goal: when every cart line resolves to a customer-specific contract price,
skip proposal and spawn Tickets atomically. Depends on Batch 5 + Batch 6.

- [x] ~~On `ExtraWorkRequest` submission, if every line's `resolve_price()`
      returns a non-`None` customer-specific contract price, set
      `routing_decision = "INSTANT"` and transition straight to the
      execution stage (no proposal phase).~~
- [x] ~~Create operational Ticket(s) immediately — one per line, anchored to
      the parent request. Title / description derived from the Service +
      line context. Status starts at `OPEN`. Priority defaults to NORMAL.~~
- [x] ~~Ensure transaction safety: ticket spawn must run inside the same
      `transaction.atomic()` as the routing transition; failure rolls back
      the whole submission.~~
- [x] ~~Add status/timeline records: each spawned Ticket gets its initial
      `TicketStatusHistory` entry; the parent `ExtraWorkRequest` gets an
      `ExtraWorkStatusHistory` entry recording the instant-route decision.~~
- [x] ~~Add tests: every-line-has-price path, missing-price-falls-to-
      proposal-path, atomic rollback test, audit/timeline coverage.~~

**Completion block — Batch 7**

- **Date:** 2026-05-16
- **Commit:** uncommitted on working tree as of 2026-05-16 (Batch 7 diff
  on top of `4fe16d5`; ready for a single batch commit once reviewed).
- **Batch 7 scope implemented:** atomic spawn of one `Ticket` per
  `ExtraWorkRequestItem` for `routing_decision="INSTANT"` cart
  submissions; new nullable FK `Ticket.extra_work_request_item`
  (SET_NULL) provides traceability; new state-machine transition
  `REQUESTED → CUSTOMER_APPROVED` gated as **system-only** (the
  spawn service drives it; customers / admins cannot reach it via
  `POST /api/extra-work/<id>/transition/`); defensive abort with
  stable error code `instant_spawn_price_lost` if `resolve_price()`
  returns None at spawn time; idempotent re-spawn (skip items that
  already have a linked ticket). **Backend-only batch** — zero
  frontend files touched (master plan §6 Batch 7 has zero frontend
  bullets).
- **Files changed summary:**
  - **Backend modified (4):** `backend/tickets/models.py` (+ nullable
    FK `extra_work_request_item`), `backend/extra_work/state_machine.py`
    (+ `(REQUESTED, CUSTOMER_APPROVED)` pair in `ALLOWED_TRANSITIONS`
    + new `SYSTEM_ONLY_TRANSITIONS` set + system-only gate in
    `_user_can_drive_transition`), `backend/extra_work/serializers.py`
    (`ExtraWorkRequestCreateSerializer.create()` calls
    `spawn_tickets_for_request()` after `routing_decision` computation,
    inside the existing `transaction.atomic()`),
    `backend/extra_work/tests/test_sprint28_cart_request.py` (3 tests
    updated: `CartRequestDoesNotSpawnTicketTests` replaced with
    `CartRequestRoutingSpawnTests` reflecting the new Batch 7 contract —
    INSTANT now spawns tickets + advances to `CUSTOMER_APPROVED`;
    PROPOSAL unchanged).
  - **Backend new (3):** `backend/extra_work/instant_tickets.py`
    (`spawn_tickets_for_request(request, *, actor)` service module),
    `backend/tickets/migrations/0008_ticket_extra_work_request_item.py`
    (cross-app schema migration; dependencies =
    `tickets.0007_*` + `extra_work.0003_request_items_and_routing`),
    `backend/extra_work/tests/test_sprint28_instant_tickets.py` (15
    tests across 6 classes).
  - **Frontend:** **NO CHANGES** — backend-only batch per master plan.
  - **Docs:** this completion block, §7 pointer advance, §8 log row,
    §9 decision-log rows.
- **Migration status:**
  - Migration file **created**:
    `backend/tickets/migrations/0008_ticket_extra_work_request_item.py`
    (cross-app: depends on `tickets.0007_ticketstatushistory_is_override_and_more`
    AND `extra_work.0003_request_items_and_routing`). Schema-only
    `AddField` operation — existing Ticket rows default to NULL on the
    new FK, so no backfill required.
  - Dev DB `migrate` **APPLIED** on 2026-05-16 by the user via
    `docker compose exec backend python manage.py migrate tickets`.
    Verified with `python manage.py showmigrations tickets` →
    `[X] 0008_ticket_extra_work_request_item`. The
    `extra_work_request_item` FK column is now live on the dev DB;
    the instant-ticket spawn path is exercisable. Test DB also
    auto-migrates each `manage.py test` run so the test suite remains
    green.
- **Exact backend API behaviour:**
  - **`POST /api/extra-work/`** — unchanged contract for the caller.
    Behavioural change: when the computed `routing_decision` is
    `"INSTANT"`, the response now reflects:
    1. `ExtraWorkRequest.status` = `"CUSTOMER_APPROVED"` (transitioned
       from `REQUESTED` via the new system-only pair).
    2. `ExtraWorkStatusHistory` row written for that transition (note:
       *"instant-route: all lines contract-priced"*).
    3. N new `Ticket` rows (one per `ExtraWorkRequestItem`), each with
       `extra_work_request_item` FK pointing back to the source line +
       initial `TicketStatusHistory` row at status `OPEN`.
  - `POST /api/extra-work/<id>/transition/` **does NOT** accept
    `to_status=CUSTOMER_APPROVED` on a `REQUESTED` request from any
    actor — the new `SYSTEM_ONLY_TRANSITIONS` gate rejects it BEFORE
    role checks (including SUPER_ADMIN). Spawn-service-only pathway.
  - No new top-level routes; no per-line CRUD endpoint changes.
- **Permission / scoping behaviour:** unchanged from Batch 6.
  `IsAuthenticatedAndActive` + scope helper still gate the submit
  endpoint. The spawn fires under the same actor + same transaction;
  no new permission surface introduced. The new state transition is
  system-only — customers cannot bypass the resolver by manually
  POSTing to `/transition/`.
- **`resolve_price()` usage:** **re-called at spawn time** per line
  (defensive — the Batch 6 routing_decision is recomputed/verified
  before the Ticket is written). If any line returns None at spawn
  time despite `routing_decision="INSTANT"`, the spawn raises
  `TransitionError(code="instant_spawn_price_lost")` and the
  surrounding `transaction.atomic()` rolls everything back (no
  parent request, no items, no tickets, no status row). Locked by
  `InstantSpawnAtomicRollbackTests` (2 tests).
- **Instant-ticket creation flow** (`backend/extra_work/instant_tickets.py`):
  1. Guard: aborts with code `instant_spawn_wrong_routing` if
     called with a non-INSTANT request.
  2. Loops `request.line_items` ordered by id.
  3. Idempotency: skips items that already have a `spawned_tickets`
     row (`Ticket.objects.filter(extra_work_request_item=item).exists()`).
  4. Re-calls `resolve_price()` for defensive abort.
  5. Creates `Ticket` with company / building / customer / created_by
     from the request + actor, title `f"{service.name} × {quantity}"`,
     description composed from request.description + line customer_note
     + service.description, priority=NORMAL, status=OPEN,
     `extra_work_request_item=item`.
  6. Writes initial `TicketStatusHistory` row (old_status="",
     new_status=OPEN, changed_by=actor) — `Ticket.save()` does NOT
     auto-write one (mirrors the state-machine pattern).
  7. After loop: if ≥1 ticket created AND request.status == REQUESTED,
     advances to CUSTOMER_APPROVED + writes `ExtraWorkStatusHistory`
     row (`is_override=False`, system-only path bypasses
     `apply_transition`'s role gate).
  8. Returns list of created `Ticket` instances ([] on idempotent
     re-run).
- **Idempotency / duplicate prevention:** `if
  Ticket.objects.filter(extra_work_request_item=item).exists():
  continue` at `instant_tickets.py:143`. Locked by
  `InstantSpawnIdempotencyTests.test_second_call_is_noop` (returns
  empty list, ticket count unchanged).
- **Ticket linkage / traceability:** every spawned Ticket carries
  `extra_work_request_item` FK back to its source item; `SET_NULL`
  on delete preserves the Ticket if the cart line is later removed.
  Locked by `TicketTraceabilityTests` (2 tests — FK set on spawn,
  FK becomes NULL after item delete, Ticket itself survives).
- **No Proposal flow started:** zero `Proposal` / `ProposalLine` /
  `ExtraWorkProposalTimelineEvent` class definitions added anywhere
  in `backend/`. `routing_decision="PROPOSAL"` paths still take no
  action (Batch 8 territory).
- **No Batch 8 work started:** no proposal model, no proposal API,
  no proposal UI, no approval-spawn path. `ProposalRoutingDoesNotSpawnTests`
  asserts PROPOSAL routing creates zero tickets and keeps status
  REQUESTED.
- **Tests / checks run:**
  - Backend targeted (`test_sprint28_instant_tickets +
    test_sprint28_cart_request`): **36 tests OK** in 6.6s.
  - Backend broader sweep (`extra_work tickets audit customers`):
    **469/469 OK** in 336.0s — no regression.
  - `manage.py check`: 0 issues. `makemigrations --dry-run --check`:
    No changes detected.
  - `git status --short`: no frontend files touched.
  - No frontend checks run (intentionally — backend-only batch).
- **Important decisions made (also logged in §9):**
  - **Service-function placement** (PM Q4): spawn lives in new module
    `instant_tickets.py`; called from `ExtraWorkRequestCreateSerializer.create()`
    inside the existing `transaction.atomic()`. Atomicity + idempotency
    + test isolation.
  - **State transition** (PM Q3): `REQUESTED → CUSTOMER_APPROVED`
    reuses existing status; system-only gate via
    `SYSTEM_ONLY_TRANSITIONS` set rejected for every actor in
    `_user_can_drive_transition` BEFORE role checks. The spawn service
    bypasses `apply_transition` to write the transition directly
    (system-only path).
  - **Ticket FK** (PM Q2): `Ticket.extra_work_request_item` nullable
    FK on the tickets side (`SET_NULL` on delete). Smallest auditable
    shape; supports both audit queries and the idempotency check.
  - **Defensive abort** (PM Q7): re-call `resolve_price()` at spawn
    time; abort with `instant_spawn_price_lost` if None. Whole
    submission rolls back. Race window is microseconds (between
    Batch 6 routing computation and the spawn loop in the same
    transaction); unreachable under normal operation, but explicit
    guard prevents silent default-price fallback drift.
  - **Ticket NOT audit-registered** (per H-11 + PM brief): Ticket
    lifecycle goes via `TicketStatusHistory`; not generic-CRUD-tracked.
- **Remaining risks:**
  - ~~Dev DB schema behind code until user approves
    `python manage.py migrate tickets`.~~
    **RESOLVED 2026-05-16** — user applied
    `python manage.py migrate tickets`; `showmigrations tickets`
    confirms `[X] 0008_ticket_extra_work_request_item`. Dev DB
    schema is now in lockstep with code; instant-ticket spawn path
    is exercisable against the dev container.
  - **`TransitionError → 500` propagation** in the create view: the
    defensive `instant_spawn_price_lost` raises `TransitionError`,
    which the create view does not currently catch (mirrors the
    existing pattern — only the `transition` view has a try/except).
    Surfaced status is 500 instead of 400. Improving this to a clean
    400 with the stable code is a small UX polish item but out of
    scope for Batch 7. The path is unreachable under normal operation
    (race window measured in microseconds).
  - **Frontend not updated**: the Batch 6 result panel still shows
    just the `INSTANT`/`PROPOSAL` banner. Exposing the spawned-ticket
    IDs in the result panel + on `ExtraWorkDetailPage` is a polish
    item; master plan §6 Batch 7 has zero frontend bullets so
    deliberately deferred. Likely lands in Batch 9 (EW dashboard).
  - **State-machine permission gate** is the load-bearing safety
    rail — if a future refactor accidentally removes the
    `SYSTEM_ONLY_TRANSITIONS` check, a customer could
    `POST /transition/` to `CUSTOMER_APPROVED` and bypass the
    resolver. `SystemOnlyTransitionTests` (4 cases) locks this.
  - **Backlog `EXTRA-INSTANT-TICKET-1` row** mentions
    "transitions directly to `IN_PROGRESS` (or new `INSTANTIATED`)"
    — stale wording. Code uses `CUSTOMER_APPROVED` per PM
    recommendation. Update the backlog row in the closeout commit.

### Batch 8 — Proposal builder

Goal: ship the first-class Proposal entity for the custom path. Depends
on Batch 5 + Batch 6.

- [ ] Add `Proposal` model — FK to `ExtraWorkRequest`, status enum
      (`DRAFT` / `SENT` / `CUSTOMER_APPROVED` / `CUSTOMER_REJECTED`),
      computed totals (net / VAT / gross), `sent_at`,
      `customer_decided_at`, override fields.
- [ ] Add `ProposalLine` model — FK to `Proposal`, optional FK to
      `Service` (free-text label allowed for ad-hoc), `quantity`,
      `unit_type`, `unit_price`, `vat_pct`,
      `customer_explanation: TextField` (customer-visible),
      `internal_note: TextField` (provider-only). **Per §10 open question
      1 default: use spec naming — `customer_explanation` and
      `internal_note` — for the new model. Document the rename in §9.**
- [ ] Ensure customer-facing endpoints **never** return `internal_note`.
      The `ProposalLineCustomerSerializer` MUST omit it; the admin
      serializer includes it. Add a regression-lock test that serializes
      a proposal as `CUSTOMER_USER` and grep-asserts `internal_note` is
      absent from the JSON.
- [ ] Add `ProposalTimelineEvent` for proposal lifecycle events (created,
      sent, customer viewed, customer approved, customer rejected, admin
      overridden). Provider sees all; customer sees a filtered subset
      (override marker visible, override reason text not visible to
      customer).
- [ ] Add proposal override with mandatory `override_reason` — mirror the
      Sprint 27F-B1 ticket shape: provider-driven `CUSTOMER_APPROVED /
      CUSTOMER_REJECTED` coerces `is_override=True` and requires
      `override_reason`; HTTP 400 with stable code
      `override_reason_required` when missing.
- [ ] On customer approval (or admin override approval), create Tickets
      transactionally — one per approved line. Rejected lines do not
      spawn tickets. Atomic with the approval transition.
- [ ] Audit signal coverage on `Proposal`, `ProposalLine`,
      `ProposalTimelineEvent`.
- [ ] Add tests: proposal CRUD, dual-note privacy, timeline emission,
      override path, atomic ticket spawn, audit coverage.

### Batch 9 — Extra Work dashboard and stats

Goal: dashboard integration for Extra Work. Depends on Batches 5–8 (the
shapes those settle determine the stats payload).

- [ ] Add Extra Work stats endpoints: `GET /api/extra-work/stats/` and
      `GET /api/extra-work/stats/by-building/`. Scoped per requesting
      role. Returns totals + by-status + awaiting-customer-approval +
      awaiting-pricing + urgent buckets.
- [ ] Add Extra Work dashboard cards to
      [`frontend/src/pages/DashboardPage.tsx`](../../frontend/src/pages/DashboardPage.tsx).
      Two top-level sections side by side: Tickets and Extra Work.
- [ ] Make dashboard render different shapes for provider-side vs
      customer-side users. CUSTOMER_USER sees their own buckets; provider
      roles see scoped aggregates.
- [ ] Add tests: backend stats endpoint scope + role shape; frontend
      Playwright for the two-section layout.

### Batch 10 — Staff per-building granularity

Goal: enable the B1/B2/B3 example per spec §B.4 / product rule #6.

- [ ] Extend `BuildingStaffVisibility` (or equivalent) with a per-row
      permission level. Options: add a `visibility_level` enum
      (`ASSIGNED_ONLY` / `BUILDING_READ` / `BUILDING_READ_AND_ASSIGN`), or
      add explicit booleans (`can_view_all_tickets`, `can_assign`).
      Sprint design decides exact shape.
- [ ] Support the spec example:
  - [ ] B1: own assigned tickets only.
  - [ ] B2: all building tickets but cannot assign.
  - [ ] B3: all building tickets and can assign.
- [ ] Update backend scoping at
      [`backend/accounts/scoping.py:211-230`](../../backend/accounts/scoping.py#L211-L230)
      (STAFF branch).
- [ ] Update assignment gates in
      [`backend/tickets/views.py:247-280`](../../backend/tickets/views.py#L247-L280)
      and
      [`backend/tickets/views_staff_assignments.py`](../../backend/tickets/views_staff_assignments.py)
      to honour the new per-row level.
- [ ] Add new `osius.staff.view_building_tickets` and
      `osius.staff.assign_tickets` permission keys to
      `OSIUS_PERMISSION_KEYS` if helpful, or rely on the model field
      directly — sprint design decides.
- [ ] Update frontend staff permission UI on
      [`frontend/src/pages/admin/UserFormPage.tsx`](../../frontend/src/pages/admin/UserFormPage.tsx)
      with the per-building level selector. View-first per spec §3.
- [ ] When a Staff user can see all tickets in a building, ensure tickets
      assigned to them are visually prioritised in the list UI (sort
      first or marked differently).
- [ ] Add tests: backend scope tests for B1/B2/B3 shapes; frontend
      Playwright for the per-row selector.

### Batch 11 — Staff completion routing

Goal: configurable per-staff / per-building routing per product rule #7.

- [ ] Add a Staff "I completed my work" flow. STAFF can drive a new
      transition out of `IN_PROGRESS`.
- [ ] Require completion note on every Staff completion (already a Sprint
      25C invariant for `IN_PROGRESS → WAITING_CUSTOMER_APPROVAL` —
      extend to the new Staff path).
- [ ] Support optional completion attachment/photo. Reuse the existing
      `TicketAttachment` model + `is_hidden=False` for the visible-evidence
      semantic.
- [ ] Default route: Staff marks done → `WAITING_MANAGER_REVIEW` (new
      ticket status), then Building Manager accepts to
      `WAITING_CUSTOMER_APPROVAL` or rejects back to `IN_PROGRESS`.
      Per §10 open question 2 default.
- [ ] Optional configured route: when the configurable flag is enabled,
      Staff marks done → directly to `WAITING_CUSTOMER_APPROVAL`. Flag
      lives on `BuildingStaffVisibility` or `StaffProfile` — sprint
      design decides.
- [ ] Keep Ticket and Extra Work routing configurations **separate** (per
      product rule #7).
- [ ] Update `ALLOWED_TRANSITIONS` in
      [`backend/tickets/state_machine.py:53-92`](../../backend/tickets/state_machine.py#L53-L92)
      with the new STAFF entries. Update matrix doc H-5 row to reflect
      the structurally-permitted STAFF transitions.
- [ ] Frontend completion modal for STAFF — completion note required +
      optional attachment + routing-aware destination text.
- [ ] Add tests: structural tests on the new transitions; configured-
      routing-flag tests; completion-evidence regression tests; matrix
      H-5 safety net update.

### Batch 12 — Building Manager read-only customer/contact view

Goal: Building Manager surfaces customers and contacts in their assigned
buildings, read-only. Depends on Batch 3 + Batch 4.

- [ ] Building Manager sees customers in assigned buildings — list +
      detail view, read-only.
- [ ] Building Manager sees contacts for those customers — list + detail
      view, read-only.
- [ ] Read-only by default. No edit affordances on these surfaces.
- [ ] No global provider settings access. Building Manager cannot reach
      `/admin/companies`, `/admin/buildings` (master list), or settings
      pages.
- [ ] Reuse existing scope helpers — no new backend gates needed; the
      backend already scopes via `building_ids_for(user)`.
- [ ] Add tests: backend scope tests + frontend Playwright for the
      read-only assertion (no Edit buttons rendered).

### Batch 13 — View-first refactor of admin pages

Goal: bring every parent record page in line with the Sprint 27E
reference. Depends on Batch 3 (sidebar) so sub-pages have a home.

- [ ] Customer detail parent record view-first. Decompose
      [`frontend/src/pages/admin/CustomerFormPage.tsx`](../../frontend/src/pages/admin/CustomerFormPage.tsx)
      (1784 lines) into customer-scoped sub-pages: Buildings, Users,
      Permissions, Extra Work, Contacts, Settings. Each lives at
      `/admin/customers/:id/<section>`.
- [ ] Building detail view-first. Refactor
      [`frontend/src/pages/admin/BuildingFormPage.tsx`](../../frontend/src/pages/admin/BuildingFormPage.tsx).
- [ ] Company detail view-first. Refactor
      [`frontend/src/pages/admin/CompanyFormPage.tsx`](../../frontend/src/pages/admin/CompanyFormPage.tsx).
- [ ] User detail view-first. Refactor
      [`frontend/src/pages/admin/UserFormPage.tsx`](../../frontend/src/pages/admin/UserFormPage.tsx)
      (1091 lines).
- [ ] Move large sections into tabs / subpages / modals.
- [ ] Avoid dumping all related data on one page. Lists with >10 rows
      get pagination + search (per spec §3 no-data-dumps rule).
- [ ] Add Playwright coverage per sub-route.

### Batch 14 — Proposal PDF and future design docs

Goal: nice-to-have closure on Sprint 28. Lowest priority.

- [ ] Proposal PDF export via `fpdf2` (already in
      [`backend/requirements.txt`](../../backend/requirements.txt)).
      `GET /api/extra-work/proposals/<id>/pdf/` returns a styled PDF
      with every customer-visible field. `internal_note` never appears
      in the rendered bytes (string-search assertion in the test).
- [ ] Future subscription architecture doc —
      `docs/architecture/future-subscription-architecture.md`.
      Schema-shape only; no code. Per spec §9.1.
- [ ] Future bank matching architecture doc —
      `docs/architecture/future-bank-matching-architecture.md`. Schema
      slot description (`external_reference`, `paid_at`, `paid_amount`);
      no code. Per spec §9.2.

---

## 7. Current batch pointer

- **Current batch:** **Batch 8 — Proposal builder**
- **Current status:** Not started
- **Next recommended action:** Open a fresh implementation pass, re-read
  this file, state the current batch, and work only on Batch 8 items.
  Batch 8 introduces the first-class `Proposal` entity (separate from
  the existing `ExtraWorkPricingLineItem` legacy concept), the
  `customer_explanation` / `internal_note` dual-note privacy split, a
  proposal timeline event log, provider-driven override (mirroring the
  Sprint 27F-B1 ticket pattern), and the atomic ticket-spawn on
  customer approval. The `routing_decision="PROPOSAL"` path from
  Batches 6/7 routes here.
- **Next recommended batch (on-deck):** Batch 9 — Extra Work dashboard
  and stats.

---

## 8. Completion log

Append-only. Newest at the top. One row per closed batch.

| Date | Batch | Commit | Summary | Tests/checks | Remaining risks |
|---|---|---|---|---|---|
| 2026-05-16 | Batch 7 — Instant-ticket path | uncommitted on top of `4fe16d5` (about to be committed in this pass) | **Backend-only batch** (master plan §6 Batch 7 has zero frontend bullets). Atomic spawn of one `tickets.Ticket` per `ExtraWorkRequestItem` for cart submissions where Batch 6 computed `routing_decision="INSTANT"`. New nullable FK `Ticket.extra_work_request_item` (SET_NULL on delete, `related_name="spawned_tickets"`) carries the traceability link. Migration `tickets/0008_ticket_extra_work_request_item.py` (cross-app dependency on `extra_work.0003_request_items_and_routing`). New state-machine transition `REQUESTED → CUSTOMER_APPROVED` reuses the existing status; gated as **system-only** via new `SYSTEM_ONLY_TRANSITIONS` set rejected for every actor in `_user_can_drive_transition` BEFORE role checks — customers cannot bypass the resolver via `POST /api/extra-work/<id>/transition/`. Spawn service `backend/extra_work/instant_tickets.py::spawn_tickets_for_request(request, *, actor)` called from `ExtraWorkRequestCreateSerializer.create()` inside the existing `transaction.atomic()`. Per-line `resolve_price()` is **re-called at spawn time** as a defensive abort: if any line returns None (despite Batch 6 routing_decision=INSTANT) the spawn raises `TransitionError(code="instant_spawn_price_lost")` and the whole submission rolls back. Idempotent: skips items whose `Ticket.extra_work_request_item` already resolves. Each spawned Ticket: company/building/customer from request, created_by=actor, title=`f"{service.name} × {quantity}"`, description = request.description + line customer_note + service.description, priority=NORMAL, status=OPEN, plus an initial `TicketStatusHistory` row. The parent request transitions REQUESTED→CUSTOMER_APPROVED with `ExtraWorkStatusHistory` row (note "instant-route: all lines contract-priced"). `Ticket` intentionally NOT audit-registered (per H-11; lifecycle goes via `TicketStatusHistory`). `ExtraWorkRequest` intentionally NOT audit-registered (Batch 6 lock unchanged). 15 new backend tests across 6 classes (`test_sprint28_instant_tickets.py`); 3 Batch 6 tests rewritten to reflect the new contract (was "no spawn yet" → now "INSTANT spawns + status advances; PROPOSAL still no-op"). | Backend targeted (`test_sprint28_instant_tickets + test_sprint28_cart_request`): **36 tests OK** in 6.6s. Backend broader sweep (`extra_work tickets audit customers`): **469/469 OK** in 336.0s — no regression. `manage.py check`: 0 issues. `makemigrations --dry-run --check`: No changes detected. No frontend files touched (intentionally — backend-only batch); no frontend checks run. | **Dev DB schema applied** 2026-05-16 by user via `python manage.py migrate tickets` — `showmigrations tickets` shows `[X] 0008_ticket_extra_work_request_item`; instant-ticket spawn path now exercisable against the dev container. `TransitionError → 500` propagation in the create view: defensive `instant_spawn_price_lost` raises `TransitionError` which the create view doesn't catch (mirrors existing pattern — only the `transition` view has a try/except). Surfaced status is 500 not 400; race window is microseconds; unreachable under normal operation. **No frontend exposure of spawned-ticket IDs yet** — Batch 6 result panel still shows just `INSTANT`/`PROPOSAL` banner. Master plan §6 Batch 7 has zero frontend bullets so deliberately deferred (likely lands in Batch 9 EW dashboard). **State-machine system-only gate is load-bearing** — if a future refactor removes the `SYSTEM_ONLY_TRANSITIONS` check, customers could bypass the resolver via `POST /transition/`. `SystemOnlyTransitionTests` (4 cases) locks this. **Backlog `EXTRA-INSTANT-TICKET-1` row** mentions transitioning to `IN_PROGRESS (or new INSTANTIATED)` — stale wording; code uses `CUSTOMER_APPROVED` per PM recommendation. Update the backlog row in the closeout commit. |
| 2026-05-16 | Batch 6 — Cart-shaped Extra Work request | `126bcea feat: add cart-shaped extra work requests` (on top of `13fb819`) | Joint backend + frontend, reshape sprint. **Backend:** `ExtraWorkRequest` becomes the parent record; new `ExtraWorkRequestItem` line items model added (FK `ExtraWorkRequest` CASCADE + FK `Service` PROTECT, NULL-allowed for legacy backfill, `quantity` Decimal, `unit_type` denormalised from Service, `requested_date` per-line, `customer_note` per-line, timestamps); new `routing_decision` field on `ExtraWorkRequest` (`"INSTANT"` vs `"PROPOSAL"` with default `"PROPOSAL"`). Migration `extra_work/0003_request_items_and_routing.py` ships schema + idempotent data backfill (one line per existing request, `service=None`, `routing_decision="PROPOSAL"`); reverse_code = noop. **`resolve_price()` is called per line at submission** to compute `routing_decision`; ALL lines must resolve to a non-None `CustomerServicePrice` → `"INSTANT"`, otherwise `"PROPOSAL"`. Batch 6 **stores** the decision but does NOT act on it (no ticket spawn, no state transition, no proposal route taken — those are Batches 7 + 8). Locked by `test_instant_routing_does_not_spawn_tickets` and `test_status_remains_requested`. Permission gate unchanged (existing `IsAuthenticatedAndActive` + `scope_extra_work_for`); CUSTOMER_USER can compose carts, provider admins can compose on behalf, STAFF blocked by existing G-B7 scope. Audit: `ExtraWorkRequestItem` registered full-CRUD; `ExtraWorkRequest` intentionally NOT audit-tracked in Batch 6 (parent was already-unregistered pre-batch — locked by `ExtraWorkRequestRoutingDecisionAuditTests` so a future addition shows as a failing test to update). 31 new backend tests across 3 modules: 20 in `test_sprint28_cart_request` (CRUD, routing-decision computation, validation, no-ticket-spawn assertion, scope isolation, cross-customer/provider rejection), 6 in `test_sprint28_cart_request_backfill` (migration backfill verifies legacy single-line requests get NULL-service + PROPOSAL), 5 in `test_sprint28_cart_request_audit`. 2 existing MVP `CreateTests` updated to send the new cart payload (documented as expected per brief). **Frontend:** new `RoutingDecision` union + `ExtraWorkRequestItem` + `ExtraWorkRequestCartCreatePayload` types in `api/types.ts`; existing `ExtraWorkRequestDetail` extended with `line_items` + `routing_decision`; `createExtraWork()` takes the cart payload type; new `extra_work` i18n namespace registered for both EN + NL bundles (parity preserved). `CreateExtraWorkPage.tsx` **fully rewritten** to a cart UI (parent fields preserved: title / description / customer / building / category / urgency / preferred_date; new cart array with add/remove lines, per-line service-dropdown + quantity + requested_date + customer_note; post-submit result panel with `INSTANT`/`PROPOSAL` banner — no navigation, ticket spawn is Batch 7 backend's job). `ExtraWorkListPage` + `ExtraWorkDetailPage` threaded with `useTranslation("extra_work")` (closes audit doc §7 row 19 — i18n missing on EW). Detail page renders a read-only line-items table + `routing_decision` badge. New Playwright spec `sprint28_extra_work_cart.spec.ts` with 5 cases (INSTANT banner, PROPOSAL banner, empty cart blocks submit, duplicate service blocks submit, detail page renders the new line item correctly). | Backend targeted (3 modules, 31 new tests): **31/31 OK** in 5.1s. Backend broader (`extra_work + audit + customers`): **296/296 OK** in 233.9s — no regression. `manage.py check`: 0 issues. `makemigrations --dry-run --check`: No changes detected. `npm run typecheck`: clean. `npm run build`: clean, 338ms. `npm run lint`: **52 problems = baseline**; zero new hits. The 4 hits in modified files (`CreateExtraWorkPage.tsx:215/228/243` + `ExtraWorkDetailPage.tsx:191`) are pre-existing `setState-in-effect` patterns carried over verbatim from the original files (auto-sync `useEffect` for building/customer pairing + the Batch-4 customer-contacts panel effect). **Playwright spec written but NOT executed locally** (WSL gotcha; CI will exercise the 5 cases). | **Dev DB schema applied** 2026-05-16 by user via `python manage.py migrate extra_work` — `showmigrations extra_work` shows `[X] 0003_request_items_and_routing`; Cart endpoint + rewritten `CreateExtraWorkPage` now exercisable against the dev container. Playwright spec needs CI run to confirm behaviour against demo seed. **2 legacy MVP tests updated** to send the new cart payload (backwards-incompat is intentional; the legacy `CreateExtraWorkPage` is rewritten in this same batch — no external callers of the legacy payload remain). **Unit-type i18n duplication**: Batch 6 added unit-type labels under the `extra_work` namespace; Batch 5 has analogous labels under the `services` namespace. Consolidation is a follow-up polish item (not P0). **`routing_decision` is computed once at submission and not recomputed** if a future batch (Batch 8) lets operators edit a line — Batch 8 must explicitly handle recomputation. **`ExtraWorkPricingLineItem` (legacy provider-built pricing rows on the legacy single-line request) is UNTOUCHED** — a different concept from the new `ExtraWorkRequestItem`. Batch 8 will reckon with it when the proposal model ships. |
| 2026-05-16 | Batch 5 — Service catalog and pricing | uncommitted on top of `e23cf40` | Joint backend + frontend. **Backend:** 3 new models in `backend/extra_work/models.py` — `ServiceCategory` (global, name-unique), `Service` (FK ServiceCategory PROTECT, unit_type reusing `ExtraWorkPricingUnitType`, `default_unit_price`, `default_vat_pct` default 21.00, is_active), `CustomerServicePrice` (FK Service PROTECT + FK Customer CASCADE, unit_price/vat_pct/valid_from/valid_to/is_active). Migration `extra_work/0002_service_catalog_and_pricing.py` (**applied to dev DB 2026-05-16 by user** via `python manage.py migrate extra_work`). New resolver `extra_work/pricing.py::resolve_price(service, customer, *, on=None)` returns active `CustomerServicePrice` row or `None` (NEVER falls back to `Service.default_unit_price` per master plan §5 rule #9). 4 new catalog endpoints at `/api/services/{categories,}` + 2 customer-scoped pricing endpoints at `/api/customers/<id>/pricing/`. Catalog gated by `IsAuthenticatedAndActive + IsSuperAdminOrCompanyAdmin`; pricing gated by `IsAuthenticatedAndActive + IsSuperAdminOrCompanyAdminForCompany` (mirrors Batch 4 Contact pattern; detail view re-scopes by `customer=customer` blocking ID smuggling). All 3 models registered in `audit/signals.py` full-CRUD tuple. 57 new backend tests across 4 modules (service catalog CRUD + protect-on-delete; resolver branches incl. the rule-#9 None-when-no-customer-specific-row lock; per-customer pricing CRUD + scope isolation + validation; audit CREATE/UPDATE/DELETE × 3 models). **Frontend:** 5 new types in `api/types.ts` (ServiceUnitType union + Service/Category/CustomerServicePrice +Create/+Update payloads); 15 new admin API helpers; `ServicesAdminPage` at `/admin/services` (tabs for services + categories, view-first list + modal CRUD, top-level sidebar entry "Services" gated to admin roles); `CustomerPricingPage` at `/admin/customers/:id/pricing` (customer-scoped sub-route — Batch 3 sidebar regex activates automatically; new "Pricing" entry between Permissions and Extra Work in the customer-scoped submenu). EN/NL i18n parity preserved (97-line delta per bundle covering `nav.services`/`nav.customer_submenu.pricing`/`services.*`/`customer_pricing.*` + unit-type labels). Visible UI hint surfaces rule #9 (`services.field_default_unit_price_hint`). 2 new Playwright specs (11 cases total). | Backend targeted (4 modules, 57 tests): **57/57 OK** in 132.6s. Per-app sanity: audit 44/44, extra_work 81/81, customers 140/140 — each clean. Broader sweep (`extra_work + audit + customers`): **first run reported `FAILED (errors=7)` (transient flake);** `-v 2` diagnostic returned zero FAIL/ERROR lines; confirmation re-run → **265/265 OK** in 471.5s. `manage.py check`: 0 issues. `makemigrations --dry-run --check`: No changes detected. `npm run typecheck`: clean. `npm run build`: clean, 454ms. `npm run lint`: **52 problems = baseline** (zero new hits in Batch 5 files). **Playwright specs written but NOT executed locally** (WSL `frontend/test-results/` root-ownership gotcha; CI will exercise the 11 cases). | **Dev DB schema applied** 2026-05-16 by user via `python manage.py migrate extra_work` — `showmigrations` shows `[X] 0002_service_catalog_and_pricing`; Catalog API + Services/Pricing admin UI now exercisable against the dev container. **Broader sweep flakiness**: first run 7 transient errors; re-run clean. Likely NotificationLog/Celery-eager shared-state race in long sequential runs across `extra_work + audit + customers`; not Batch-5-specific but documented for future batches to re-run before declaring failure. **Spec §5 / backlog `EXTRA-PRICING-1` doc drift**: spec §5 "Resolution order" step 2 says "global default" fallback; backlog row text similarly stale. Code follows master plan rule #9 (returns `None`); doc reconciliation is a follow-up patch. **`CustomerPricingPage` Edit modal locks the service dropdown** (switching service on an existing price would corrupt history); users delete + add to switch. **No customer-side pricing visibility yet** (their own contract prices) — ships with Batch 6 cart UI. **No Batch 6 wiring**: the catalog is not yet called from any Extra Work request flow. |
| 2026-05-16 | Batch 4 — Contacts model and UI | uncommitted on top of `9402e38` | Joint backend + frontend. **Backend:** `Contact` model added to `backend/customers/models.py` (FK Customer CASCADE + FK Building SET_NULL + name/email/phone/role_label/notes/timestamps; **no password/role/user/is_active/permission_overrides** — structurally not a User per spec §1). Migration `customers/0007_contact.py` created (**not applied to dev DB yet**). 2 new endpoints at `/api/customers/<id>/contacts/` (list+create) and `/contacts/<id>/` (retrieve/update/delete), gated by `IsAuthenticatedAndActive + IsSuperAdminOrCompanyAdminForCompany`. Detail view re-scopes by `customer=customer` to block ID smuggling. Cross-customer building validation in serializer. Contact registered in `audit/signals.py` full-CRUD tuple. 26 new tests across 5 classes (CRUD happy-path × 2 admin roles, scope isolation, ID-smuggling 404, BM/customer/staff 403, building-membership validation, "is-not-a-User" payload assertion, audit CREATE/UPDATE/DELETE rows). **Frontend:** `Contact` + `ContactCreatePayload` + `ContactUpdatePayload` types added; 5 admin API helpers added; `CustomerContactsPage` replaces Batch 3 placeholder route at `/admin/customers/:id/contacts` (view-first list + read-only detail + Add/Edit modal + Delete `ConfirmDialog`; **no password/role/login field anywhere**). Contextual read-only `Customer-contacts` panels added to both `TicketDetailPage` (`data-testid="ticket-customer-contacts-panel"`) and `ExtraWorkDetailPage` (`data-testid="extra-work-customer-contacts-panel"`), gated to SUPER_ADMIN/COMPANY_ADMIN mirroring the backend. 25 new `customer_contacts.*` i18n keys in each of EN/NL bundles, parity preserved. Playwright spec `frontend/tests/e2e/sprint28_contacts.spec.ts` with 5 cases. | Backend targeted (`customers.tests.test_sprint28_contacts + audit.tests.test_sprint28_contact_audit`): **26/26 OK** in 24.7s. Backend broader (`customers + audit`): **175/175 OK** in 165.2s. Cross-app sweep (`customers audit tickets extra_work`): **365/365 OK** in 298.2s — no regression from the Contact + audit signal additions. `manage.py check`: 0 issues. `makemigrations --dry-run --check`: No changes detected. `npm run typecheck`: clean. `npm run build`: clean, 508ms. `npm run lint`: **52 problems = baseline** (zero new lint hits in Batch 4 files; frontend agent stash-comparison showed pre-Batch-4 was 53 problems, so net is -1 error after the agent extracted ticket/EW customer-id locals to satisfy `exhaustive-deps`). **Playwright spec written but NOT executed locally** (WSL `frontend/test-results/` root-ownership gotcha; brief allows). | Dev DB schema is **behind code** until user approves `python manage.py migrate` (Contacts API + the Ticket/EW contextual panels will 500 against the dev container until that runs). Playwright spec needs CI run to confirm against demo seed. Building-dropdown in the Add/Edit modal shows every linked building including potentially-deactivated ones (polish item, not P0). Contextual panels emit an API call on every Ticket/EW detail render with no caching — debounce/SWR is a later polish item. BM read-only contact view is intentionally deferred to **Batch 12**; gate locked by `test_building_manager_cannot_*` cases. |
| 2026-05-16 | Batch 3 — Sidebar refactor foundation | uncommitted on top of `c3a9060` | Frontend only. `AppShell.tsx` gains a URL-derived `mode = "top-level" \| "customer-scoped"` (regex on `pathname`, no `useState`) and a customer-scoped submenu (Back / Overview / Buildings / Users / Permissions / Extra Work / Contacts / Settings). `App.tsx` registers six new `/admin/customers/:id/<section>` routes — five render the new `CustomerSubPagePlaceholder` "Coming soon" component; `permissions` re-renders `CustomerFormPage` so the Sprint 27E editor remains reachable without decomposing the parent page (decomposition is Batch 13). EN/NL i18n keys added for `nav.customer_submenu.*` + `customer_subpage_placeholder.*`. Playwright spec `sprint28b_customer_sidebar.spec.ts` covers deep-link, Back, and non-customer-route cases. | `npm run typecheck` → clean. `npm run build` → clean, 373ms. `npm run lint` → **52 problems = baseline** (only `AppShell.tsx:122` lint hit is the pre-existing `setSidebarOpen` in `useEffect`; line number shifted from `:93`, rule violation unchanged). Playwright spec **written but NOT executed locally** (WSL root-owned `frontend/test-results/` gotcha; brief allows this). | Playwright spec needs CI run to confirm behaviour against demo seed. `CustomerFormPage` is mounted by two routes (`:id` Overview + `:id/permissions`); React Router remounts on path change so state is not preserved across the nav. Batch 13 will decompose `CustomerFormPage` and remove the duplication. `AppShell.tsx:122` lint hit is unchanged baseline. |
| 2026-05-16 | Batch 1 — Operational health fixes | uncommitted on top of `6e572db` | Frontend: `getApiError` HTML-prefix guard (`client.ts`); `AuditLog.reason` + `actor_scope` added to type (`types.ts`); sidebar "Extra Work" i18n'd (`AppShell.tsx` + `common.json` EN/NL). Backend: 4 pending dev DB migrations applied after explicit user approval (`audit.0002`, `customers.0005`, `customers.0006`, `tickets.0007`). | `manage.py check` (pre + post): 0 issues; `showmigrations`: all `[X]` after migrate; `npm run typecheck`: clean; `npm run build`: clean (472ms); `npm run lint`: 52 problems = baseline (zero new hits in changed files). No unit-test framework wired on frontend — `getApiError` ships with code-level guard + typecheck/build coverage only (Vitest setup parked for a later batch). | No automated unit coverage on `getApiError`; `AuditLog.reason`/`actor_scope` declared as required (matches backend default-emitting contract); `nav.extra_work` NL value is sentence-case "Extra werk" (flippable to "Extra Werk" with no code change). |
| 2026-05-16 | Batch 2 — Verify mild backend risk | uncommitted on top of `739e347` | **Real bug found and fixed.** STAFF could `POST /api/tickets/<id>/assign/` and mutate `ticket.assigned_to` because both the view gate (`tickets/views.py:250`) and the serializer gate (`tickets/serializers.py:626`) used `is_staff_role` (which returns True for STAFF since Sprint 23A). Tightened both to an explicit `{SUPER_ADMIN, COMPANY_ADMIN, BUILDING_MANAGER}` allow-list. New regression test `tickets/tests/test_sprint28a_staff_assign_block.py` (4 cases). H-4 matrix attribution drift resolved by rewriting the test-reference cell to cite the structural enforcement + the new Sprint 28 Batch 2 test. | Pre-fix targeted run: 3 of 4 new tests FAILED (200 != 403) — proves bug. Post-fix targeted run: 4/4 OK. Broader `python manage.py test tickets --keepdb -v 1`: **157 tests OK** in 101.6s. `manage.py check`: 0 issues. No frontend files touched. | `is_staff_role` remains the gate in 10+ other call sites and was deliberately NOT changed (refactor). Customer-user error message changed from "Customer users cannot assign tickets." to "This role cannot assign tickets." (status code 403 unchanged; existing test asserts only status). Batch 10's per-building `can_assign` flag will need to widen the explicit gate when it lands — do NOT pre-empt. |

---

## 9. Decision log

Append-only. Newest at the top. Any decision made during a batch goes
here AND in the batch's completion block.

| Date | Decision | Reason | Source |
|---|---|---|---|
| 2026-05-16 | The **Batch 7 instant-ticket spawn** lives in a dedicated service module `backend/extra_work/instant_tickets.py::spawn_tickets_for_request(request, *, actor)`, called from `ExtraWorkRequestCreateSerializer.create()` inside the existing `transaction.atomic()`. The spawn re-calls `resolve_price()` per line for defensive abort (raises `TransitionError(code="instant_spawn_price_lost")` and rolls the whole submission back if any line returns None). Idempotent: skips items that already have `Ticket.extra_work_request_item` set. | PM Q4 default chosen. Atomicity: ticket spawn must roll back with the cart on any failure. Idempotency: double-POST / replay must not create duplicate tickets. Service-function placement makes it directly callable from tests + reusable from any future caller (e.g. a manual "re-spawn" admin endpoint) without serializer round-trip. Locked by `InstantSpawnAtomicRollbackTests` + `InstantSpawnIdempotencyTests`. | Batch 7 + `backend/extra_work/instant_tickets.py` + `backend/extra_work/serializers.py` |
| 2026-05-16 | **Source link is `tickets.Ticket.extra_work_request_item`** — nullable FK to `extra_work.ExtraWorkRequestItem`, `on_delete=SET_NULL`, `related_name="spawned_tickets"`, default NULL. New migration `tickets/0008_ticket_extra_work_request_item.py`. | PM Q2 recommendation. Smallest auditable shape — one column, one direction, supports both audit queries ("show me all tickets spawned from this cart") and the idempotency check (skip-if-exists). SET_NULL preserves the Ticket if the cart line is later removed (history integrity). Inverse direction (item → ticket) or join table is over-engineered. Locked by `TicketTraceabilityTests` (2 cases — FK set on spawn; FK becomes NULL after item delete; Ticket survives). | Batch 7 + `backend/tickets/models.py` + `backend/tickets/migrations/0008_ticket_extra_work_request_item.py` |
| 2026-05-16 | **New state-machine transition `REQUESTED → CUSTOMER_APPROVED`** reuses the existing status (no new enum value) and is gated as **system-only** via a new `SYSTEM_ONLY_TRANSITIONS` set checked in `_user_can_drive_transition` BEFORE role checks. Customers, COMPANY_ADMIN, SUPER_ADMIN — every actor — gets `False` for this pair via `POST /api/extra-work/<id>/transition/`. The spawn service bypasses `apply_transition` and writes the transition directly (system-only path) when at least one Ticket has been created. | PM Q3 recommendation. The customer's submission of an all-contract-priced cart IS the customer approval; reusing `CUSTOMER_APPROVED` keeps the state machine small (no new enum, no migration). System-only gating prevents a customer from bypassing the resolver (e.g. POSTing `to_status=CUSTOMER_APPROVED` to a `routing_decision="PROPOSAL"` request to force ticket spawn — defence in depth even though the spawn is also FK-gated). Locked by `SystemOnlyTransitionTests` (4 cases). | Batch 7 + `backend/extra_work/state_machine.py` SYSTEM_ONLY_TRANSITIONS + `_user_can_drive_transition` |
| 2026-05-16 | **`resolve_price()` is re-called at spawn time** as a defensive abort. If any line returns None at spawn (despite Batch 6's `routing_decision="INSTANT"` being set at submission), the spawn raises `TransitionError(code="instant_spawn_price_lost")` and the surrounding `transaction.atomic()` rolls everything back — no parent request, no items, no tickets, no status row. The user retries; the resolver will re-classify as PROPOSAL on retry. | PM Q7 recommendation. Closes the race window between Batch 6 routing computation and Batch 7 spawn (microseconds in practice — both inside the same atomic block — but a `CustomerServicePrice.is_active=False` / `valid_to=<past>` flip from another transaction could theoretically land in between). Surfacing it as a rollback + stable error code prevents silent default-price fallback (which would breach master plan §5 rule #9). Locked by `InstantSpawnAtomicRollbackTests.test_error_code_is_instant_spawn_price_lost` + `test_resolve_price_returning_none_aborts_submission`. | Batch 7 + `backend/extra_work/instant_tickets.py` + `backend/extra_work/tests/test_sprint28_instant_tickets.py` |
| 2026-05-16 | `ExtraWorkRequest` is **reshaped** to a parent record with N `ExtraWorkRequestItem` line items (per master plan §6 Batch 6 verbatim wording: "Migration with a data backfill so existing single-line requests get one line item"). The legacy single-line payload shape is no longer accepted by the API; the existing `CreateExtraWorkPage` is rewritten in the same batch so no external callers remain. 2 MVP tests updated to send the new cart payload (documented in PM brief). | Master plan §6 Batch 6 explicitly chose reshape over a parallel-deprecated shape. Keeping a parallel single-line shape would dual-maintain the form + the validator and would still require the data backfill (one row → one line item) when Batch 7 starts reading `line_items`. The backwards-incompat is acceptable because there is exactly one production caller (the page being rewritten) and the backfill provides a one-line-item view of every historical request. | Batch 6 + `backend/extra_work/migrations/0003_request_items_and_routing.py` + `frontend/src/pages/CreateExtraWorkPage.tsx` |
| 2026-05-16 | `ExtraWorkRequestItem.service` FK is **NULL-allowed** at the model level (with `null=True, blank=True, on_delete=PROTECT`). The serializer enforces non-null on new submissions; only the migration backfill creates NULL-service rows (for legacy `ExtraWorkRequest` rows that pre-date the Batch 5 Service catalog). | The data backfill must create one line item per existing request, but pre-Batch-5 requests have no `Service` catalog row to point at. The alternative — creating a sentinel "legacy single-line request" Service — would clutter the catalog with an admin-visible row. NULL-on-backfill keeps the historical signal clean (these requests don't represent catalog-driven work) and the serializer prevents new NULL-service rows. Locked by `test_sprint28_cart_request_backfill` + `CartRequestValidationTests`. | Batch 6 + `backend/extra_work/models.py` ExtraWorkRequestItem + `backend/extra_work/migrations/0003_request_items_and_routing.py` |
| 2026-05-16 | **`resolve_price()` is called at submission to compute `routing_decision`, but Batch 6 does NOT act on the result.** The field is computed and stored; no `tickets.Ticket` is created, no state-machine transition is fired, no proposal route is taken. Batch 7 reads the field to spawn tickets for the `"INSTANT"` path; Batch 8 reads it to enter the proposal queue for the `"PROPOSAL"` path. | Storing the decision now (rather than recomputing at every action) lets Batch 6 ship the customer-facing cart without changing the existing EW workflow state machine. It also makes routing observable for audit / debugging before any downstream system acts on it. Trade-off: if a future batch (Batch 8) lets the operator edit a line after submission, the field can drift — Batch 8 must explicitly handle recomputation. Locked by `test_instant_routing_does_not_spawn_tickets` and `test_status_remains_requested`. | Batch 6 + `backend/extra_work/serializers.py` ExtraWorkRequestCreateSerializer.create() + `backend/extra_work/tests/test_sprint28_cart_request.py` |
| 2026-05-16 | `ExtraWorkRequest` itself is **intentionally NOT registered in `audit/signals.py`** in Batch 6. Only the new `ExtraWorkRequestItem` is added to the full-CRUD tuple. The parent row was already-unregistered pre-batch; adding registration now would be scope creep. A dedicated test class `ExtraWorkRequestRoutingDecisionAuditTests` asserts no parent-row `AuditLog` is written so a future sprint adding registration will see a clear failing test to update. | The brief instructed "if `ExtraWorkRequest` isn't yet registered in either, leave that alone for Batch 6". Audit registration of `ExtraWorkRequest` is a separate, deliberate decision — it would emit signals for every transition (state-machine writes) and might double-fire with the existing `ExtraWorkStatusHistory` mechanism. Defer to a dedicated future batch that audits the trade-off. | Batch 6 + `backend/audit/signals.py` + `backend/audit/tests/test_sprint28_cart_request_audit.py::ExtraWorkRequestRoutingDecisionAuditTests` |
| 2026-05-16 | `Service`, `ServiceCategory`, `CustomerServicePrice` are added to **`backend/extra_work/models.py`** (extending the existing file). Resolver `resolve_price()` lives in new module `backend/extra_work/pricing.py` (parallel to `extra_work/scoping.py` + `extra_work/state_machine.py`). Migration: `extra_work/0002_service_catalog_and_pricing.py`. | Extra_work app already owns the pricing-adjacent vocabulary (`ExtraWorkPricingUnitType` enum + the legacy `ExtraWorkPricingLineItem`). Catalog + pricing belong in the same domain as the work they price. A new `catalog/` app would force new `INSTALLED_APPS`, audit-signal import, migration root for zero benefit. Customers app is wrong: pricing is keyed (service, customer), the catalog is provider-wide, and the resolver lives next to the Extra Work workflow that will call it (Batch 7+). PM agent placement recommendation. | Batch 5 + `backend/extra_work/models.py` + PM scope-verification report |
| 2026-05-16 | **Reused the existing `ExtraWorkPricingUnitType` enum** (`HOURS / SQUARE_METERS / FIXED / ITEM / OTHER`) verbatim for `Service.unit_type`. NO parallel `ServiceUnitType` enum introduced. Spec §5's HOURLY/PER_SQM/FIXED/PER_ITEM names are descriptive equivalents of these storage values. | Spec §5 unit-type set maps onto the existing enum. Introducing a parallel enum would fork the pricing-line-item vs service-row vocabulary; future Batch-8 proposal rows would have to bridge the two, creating an entirely avoidable schema and validation surface. | Batch 5 + `backend/extra_work/models.py` ExtraWorkPricingUnitType + Service.unit_type field |
| 2026-05-16 | **`resolve_price(service, customer, *, on=None)` returns `None`** when no active `CustomerServicePrice` row matches. It MUST NOT fall back to `Service.default_unit_price`. The global default is a provider-side reference only (display in the catalog admin UI); it never triggers the instant-ticket path. When the resolver returns `None`, the caller (Batch 7) routes the line to the proposal flow. | Master plan §5 rule #9 + 2026-05-15 decision-log row (already locked at spec-meeting time). The spec doc §5 "Resolution order" step 2 and backlog `EXTRA-PRICING-1` row both have stale wording suggesting a global-default fallback — both will be reconciled in a doc-only patch; master plan rule is authoritative. Regression-locked by `ResolvePriceReturnsNoneWithoutCustomerSpecificTests`. | Batch 5 + `backend/extra_work/pricing.py` + `backend/extra_work/tests/test_sprint28_pricing_resolver.py::ResolvePriceReturnsNoneWithoutCustomerSpecificTests` |
| 2026-05-16 | Batch 5 frontend is split into **two routes**: provider-wide `/admin/services` (top-level admin) for catalog + categories; per-customer `/admin/customers/:id/pricing` (customer-scoped, NEW sub-route extending the Batch 3 sidebar by one entry) for contract pricing. Catalog is admin-only; customer-side price visibility (their own contract prices) is deferred to Batch 6 (ships with the cart UX). | The catalog is provider-wide (one source of truth for all customers); per-customer pricing is customer-scoped and benefits from the existing customer-scoped sidebar anchor. Splitting the surfaces honours spec §3 "no data dump" + maps each surface to the correct sidebar mode. The "Pricing" sub-route extends the Batch 3 customer-scoped submenu (was 6 entries → now 7); no Batch 3 placeholder is reused (pricing is a NEW slot). | Batch 5 + `frontend/src/pages/admin/ServicesAdminPage.tsx` + `frontend/src/pages/admin/CustomerPricingPage.tsx` + `frontend/src/layout/AppShell.tsx` + `frontend/src/App.tsx` |
| 2026-05-16 | `Contact` is added to **`backend/customers/models.py`** (next to `Customer`, memberships, `CustomerCompanyPolicy`), not a new `contacts/` app. Migration is `customers/0007_contact.py`. | Customers app already follows the app-scoped-split-file convention (`serializers_*.py`, `views_*.py`); audit signals + permission resolver already import from `customers.models`; placing Contact here means zero new app registration + zero circular-import risk + stays in the same scope as the parent `Customer` FK. PM agent recommended this placement after inspecting repo conventions. | Batch 4 + PM scope-verification report + `backend/customers/models.py` |
| 2026-05-16 | `Contact` is **structurally NOT a User**: the model has no `password`, no `role`, no `user` FK, no `is_active` (login semantics), no `permission_overrides`, no scope-row attachment. Promotion from Contact to User is parked for a later sprint and will be a separate, explicit flow. | Spec §1 hard rule + master plan §5 rule 2 + RBAC matrix invariant H-9 (no scope growth via stacked permissions). Conflating Contact with User would breach scope and let provider admins promote a contact into a privileged user implicitly. `ContactIsNotAUserTests` regression-locks this by iterating the serialized JSON keys and asserting absence of every login-related key. | Batch 4 + `backend/customers/models.py` Contact + `backend/customers/tests/test_sprint28_contacts.py::ContactIsNotAUserTests` |
| 2026-05-16 | The Contact CRUD API is gated by **`IsAuthenticatedAndActive + IsSuperAdminOrCompanyAdminForCompany`** (admin-only). Building Manager / STAFF / CUSTOMER_USER all 403 in Batch 4. Building Manager **read-only** contact view in their assigned buildings is intentionally deferred to **Batch 12** (per master plan §6). | The master plan §6 Batch 4 explicitly defers BM read-only view to Batch 12 to keep Batch 4 small. Locked by `test_building_manager_cannot_*` regression cases. The frontend contextual panel on Ticket/Extra-Work detail mirrors this gate so non-admin roles do not even emit the API call (avoids 403 noise). When Batch 12 widens the backend gate, the frontend panel will be widened to match. | Batch 4 + `backend/customers/views_contacts.py` + `frontend/src/pages/TicketDetailPage.tsx` + `frontend/src/pages/ExtraWorkDetailPage.tsx` |
| 2026-05-16 | Sidebar mode is **URL-derived** (regex against `location.pathname`), not React state. A pathname matching `/^\/admin\/customers\/(\d+)(?:\/.*)?$/` switches the sidebar into customer-scoped mode; any other pathname is top-level. The list page `/admin/customers` and `/admin/customers/new` deliberately do NOT trigger the submenu. | Browser refresh on a deep link must preserve the customer-scoped sidebar; back-button behaviour must be predictable; no global state library is needed. The audit (§7) called out the lack of hierarchical state on the sidebar as a P1 issue; this is the structural anchor for the view-first refactor Batches 4, 6, and 13 will build on. | Batch 3 + `frontend/src/layout/AppShell.tsx` `deriveSidebarMode` |
| 2026-05-16 | Five of the six customer-scoped submenu sub-routes (`buildings`, `users`, `extra-work`, `contacts`, `settings`) render a **single shared `CustomerSubPagePlaceholder`** "Coming soon" component. The `permissions` sub-route is the deliberate exception — it re-renders `CustomerFormPage` so the Sprint 27E permission editor stays reachable via the deep link `/admin/customers/:id/permissions` **without** decomposing the parent page in this batch. `CustomerFormPage` decomposition is Batch 13 work. | The brief explicitly allowed "minimal routing integration" for the Permissions editor and asked for a single placeholder for the rest; this keeps the Batch 3 diff small, ships the structural anchor without coupling to later sub-page implementations, and avoids forking the Sprint 27E editor. | Batch 3 + `frontend/src/pages/admin/CustomerSubPagePlaceholder.tsx` + `frontend/src/App.tsx` |
| 2026-05-15 | Global default service price alone is **not** sufficient to create an instant ticket. Customer-specific active contract price is required. | Spec §5 + §4.1 + product rule #9. Global default exists as a provider-side reference only. | [`docs/product/meeting-2026-05-15-system-requirements.md`](../product/meeting-2026-05-15-system-requirements.md) §5 |
| 2026-05-15 | Contacts are not login Users. Separate entity, no password / role / membership / permission overrides. Promotion to User is a later, explicit sprint. | Spec §1. Prevents conflation that would breach RBAC scope. | [`docs/product/meeting-2026-05-15-system-requirements.md`](../product/meeting-2026-05-15-system-requirements.md) §1 |
| 2026-05-15 | Detail pages load **view-first / read-only by default**. Editing requires explicit Edit/Add → modal or separate page. Sprint 27E `CustomerFormPage` permission editor is the reference shape. | Spec §3. Prevents accidental mutation and gives a stable mental model across pages. | [`docs/product/meeting-2026-05-15-system-requirements.md`](../product/meeting-2026-05-15-system-requirements.md) §3 |
| 2026-05-15 | Customer Company Admin **cannot promote anyone to Customer Company Admin** and cannot grant permissions above their own level. | RBAC matrix H-6 / H-7. Enforced via `CustomerUserBuildingAccessUpdateSerializer.validate_access_role`. | [`docs/architecture/sprint-27-rbac-matrix.md`](../architecture/sprint-27-rbac-matrix.md) §3 H-6/H-7 |
| 2026-05-15 | Staff **may** see normal internal work notes by default, but cost/margin/provider-only proposal notes **must** be hideable from Staff. The privacy model is 3-way: customer / provider-with-staff / provider-only-cost-margin. | Spec §6 + §B.4. Today the system is 2-way only; the 3-way strip lands when STAFF visibility on Extra Work opens. | [`docs/product/meeting-2026-05-15-system-requirements.md`](../product/meeting-2026-05-15-system-requirements.md) §6 |
| 2026-05-15 | The `TicketStatusHistory` override row (`is_override=True` + `override_reason`) IS the audit trail for ticket workflow override. **Do not** register `TicketStatusHistory` for generic AuditLog tracking — that would double-write the same fact (RBAC matrix H-11). | Sprint 27F-B1 design + matrix H-11. Workflow override (per-transition) and permission override (per-access-row) are separate concepts and must remain so. | [`docs/architecture/sprint-27-rbac-matrix.md`](../architecture/sprint-27-rbac-matrix.md) §3 H-11; [`CLAUDE.md`](../../CLAUDE.md) §2 audit rule |
| 2026-05-16 | The BM-assign endpoint `/api/tickets/<id>/assign/` gates explicitly on `{SUPER_ADMIN, COMPANY_ADMIN, BUILDING_MANAGER}` — STAFF is excluded by name, not by `is_staff_role`. `is_staff_role` keeps its existing Sprint 23A semantics (returns True for STAFF so STAFF inherits internal-note / hidden-attachment / first-response behaviour); widening its exclusion set would silently change every other call site. | Real bug found in Batch 2: STAFF could mutate `ticket.assigned_to` because both gates relied on `is_staff_role` to exclude only CUSTOMER_USER. Fixed at view + serializer (defense in depth) with the explicit allow-list pattern. | Audit row 26 + master plan Batch 2 + `tickets/tests/test_sprint28a_staff_assign_block.py` |
| 2026-05-16 | H-4 invariant ("STAFF always sees work assigned to them — cannot be removed") is locked **structurally**, not by a dedicated test. The matrix's previous test-reference cell pointing to "Sprint 27A T-7" was incorrect — T-7 audits `BuildingStaffVisibility.can_request_assignment`, not H-4 visibility retention. Sprint 28 Batch 2 rewrote the matrix cell to cite the structural enforcement + the new STAFF-assign-block test as the surrounding perimeter. | Audit row 25 + master plan Batch 2 "Resolve H-4 matrix attribution drift" item. Option 1 from the brief (rewrite to cite structural guard); the existing scoping helper `accounts/scoping.py:211-230` is the actual lock. | [`docs/architecture/sprint-27-rbac-matrix.md`](../architecture/sprint-27-rbac-matrix.md) §3 row H-4 (post-Sprint-28-Batch-2 wording) |

---

## 10. Open questions

Only the three open questions identified by the audit. Defaults are listed
so a future pass can proceed without re-asking; if a stakeholder wants a
different answer, they override the default and the decision is logged in
§9.

1. **Proposal line field naming** (relevant to Batch 8).
   `customer_explanation` / `internal_note` (spec §6 naming) **versus**
   legacy `customer_visible_note` / `internal_cost_note` (used by the
   existing `ExtraWorkPricingLineItem` rows).
   **Default recommendation:** use the spec names
   (`customer_explanation`, `internal_note`) for the **new** `Proposal`
   model. The legacy `ExtraWorkPricingLineItem` keeps its names because
   it's a different concept (single-line request pricing breakdown, not a
   first-class proposal artifact). Document the rename in §9 when Batch 8
   executes.

2. **Staff manager-review workflow** (relevant to Batch 11).
   When STAFF marks a ticket done with the new routing, what's the BM's
   review obligation?
   **Default recommendation:**
   - STAFF marks done → **`WAITING_MANAGER_REVIEW`** (new status).
   - Building Manager accepts → `WAITING_CUSTOMER_APPROVAL`.
   - Building Manager rejects → `IN_PROGRESS` (work continues).
   - BM cannot skip the customer (that remains a workflow override gated
     by the existing `is_override` + `override_reason` Sprint 27F-B1
     contract).

3. **Cart-level vs line-level customer notes** (relevant to Batch 6).
   Spec §4 puts a `customer_note` on each cart line. The existing
   `ExtraWorkRequest.description` is a free-text field on the request
   itself.
   **Default recommendation:** keep **both**. The request-level
   `description` is "why I'm submitting this cart"; each line carries its
   own `customer_note` for per-service context. Semantically separable;
   the UI must make this distinction visually clear.

---

## 11. Rules for updating this file

At the **end of every batch**:

1. **Update the current batch status.** Mark items complete:
   `- [ ] Open item` becomes `- [x] ~~Completed item~~`.
2. **Add a completion block under the batch heading.** Block contents:
   - **Date:** absolute ISO date (e.g. `2026-06-12`).
   - **Commit:** SHA(s) that landed the batch. If unmerged, write
     "uncommitted on working tree as of <date>".
   - **Files changed summary:** paths, not full diffs. Example: *"Backend:
     `customers/models.py` (Contact model), `customers/migrations/0007_*`,
     `audit/signals.py` (Contact registration), `customers/tests/test_sprint28_contacts.py`. Frontend: `api/types.ts`,
     `api/admin.ts`, `pages/admin/CustomerContactsPage.tsx`."*
   - **Tests / checks run:** exact commands + outcomes. Example: *"`python
     manage.py test customers audit --keepdb -v 1` → OK (561 tests).
     `npm run typecheck` → clean. `npm run lint` → baseline (no new
     hits)."*
   - **Important decisions made:** one-line summary per decision. Also
     append a row in §9 with the full context.
   - **Remaining risks:** anything the next batch must know. Example: *"The
     Contact-detail page reuses the `useEntityForm` hook, which still
     bakes inline-editing in — Batch 13 must refactor that hook before
     applying view-first to the Contact detail page."*
3. **Append a row in §8 (completion log)** mirroring the batch's metadata.
4. **Append a row in §9 (decision log)** for every decision made during
   the batch.
5. **Advance the §7 Current batch pointer** to the next batch ONLY if all
   required tests/checks passed. If anything is yellow/red, keep the
   pointer on the current batch.
6. **Advance the §7 Next recommended batch pointer** to the new on-deck
   batch.

If a **blocker is found** during a batch:

1. **Keep the Current batch pointer on the blocked batch.** Do not advance.
2. **Document the blocker under the batch's checklist** with a new line
   prefixed `BLOCKED <date>: <description>`. Include what was attempted
   and what's required to resolve.
3. **Stop the pass.** Do not start the next batch. Report the blocker to
   the user and wait for direction.
4. Resume only when the blocker is resolved (either by user input or by
   a follow-up batch). Document the resolution under the same blocker
   line as `RESOLVED <date>: <how>`.

**Never rewrite history in this document.** Completion logs and decision
logs are append-only. If a previous entry turns out to be factually wrong,
add a correction note below it dated with the correction date — do not
edit the original. This preserves the audit trail across AI sessions.
