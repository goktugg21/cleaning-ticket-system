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

- [x] ~~Add `Proposal` model — FK to `ExtraWorkRequest`, status enum
      (`DRAFT` / `SENT` / `CUSTOMER_APPROVED` / `CUSTOMER_REJECTED`),
      computed totals (net / VAT / gross), `sent_at`,
      `customer_decided_at`, override fields.~~
- [x] ~~Add `ProposalLine` model — FK to `Proposal`, optional FK to
      `Service` (free-text label allowed for ad-hoc), `quantity`,
      `unit_type`, `unit_price`, `vat_pct`,
      `customer_explanation: TextField` (customer-visible),
      `internal_note: TextField` (provider-only). **Per §10 open question
      1 default: use spec naming — `customer_explanation` and
      `internal_note` — for the new model. Document the rename in §9.**~~
- [x] ~~Ensure customer-facing endpoints **never** return `internal_note`.
      The `ProposalLineCustomerSerializer` MUST omit it; the admin
      serializer includes it. Add a regression-lock test that serializes
      a proposal as `CUSTOMER_USER` and grep-asserts `internal_note` is
      absent from the JSON.~~
- [x] ~~Add `ProposalTimelineEvent` for proposal lifecycle events (created,
      sent, customer viewed, customer approved, customer rejected, admin
      overridden). Provider sees all; customer sees a filtered subset
      (override marker visible, override reason text not visible to
      customer).~~
- [x] ~~Add proposal override with mandatory `override_reason` — mirror the
      Sprint 27F-B1 ticket shape: provider-driven `CUSTOMER_APPROVED /
      CUSTOMER_REJECTED` coerces `is_override=True` and requires
      `override_reason`; HTTP 400 with stable code
      `override_reason_required` when missing.~~
- [x] ~~On customer approval (or admin override approval), create Tickets
      transactionally — one per approved line. Rejected lines do not
      spawn tickets. Atomic with the approval transition.~~
- [x] ~~Audit signal coverage on `Proposal`, `ProposalLine`,
      `ProposalTimelineEvent`.~~ (Implemented as: Proposal + ProposalLine
      registered for full-CRUD; ProposalTimelineEvent + ProposalStatusHistory
      intentionally NOT registered — H-11 invariant; the history rows ARE
      the workflow-override audit trail.)
- [x] ~~Add tests: proposal CRUD, dual-note privacy, timeline emission,
      override path, atomic ticket spawn, audit coverage.~~

#### Batch 8 completion (2026-05-17)

- **Date:** 2026-05-17.
- **Commit:** `ec66380 feat: add extra work proposal builder` (on top of
  `7ec3f15`).
- **Files changed (5 edits + 8 new files):**
  - **Edits:** `backend/extra_work/models.py` (+395 lines: ProposalStatus,
    ProposalTimelineEventType, Proposal, ProposalLine, ProposalStatusHistory,
    ProposalTimelineEvent); `backend/extra_work/serializers.py` (+393 lines:
    ProposalLineAdminSerializer / ProposalLineCustomerSerializer /
    ProposalCreateSerializer / ProposalDetailSerializer / ProposalListSerializer
    / ProposalTransitionSerializer / ProposalStatusHistorySerializer /
    ProposalTimelineEventAdminSerializer / ProposalTimelineEventCustomerSerializer);
    `backend/extra_work/urls.py` (+45 lines: 7 new endpoint paths);
    `backend/tickets/models.py` (+15 lines: nullable
    `Ticket.proposal_line` FK with `on_delete=SET_NULL`,
    `related_name="spawned_tickets_for_proposal_line"`);
    `backend/audit/signals.py` (+17 lines: Proposal + ProposalLine added
    to full-CRUD tuple; comment block documents the H-11 NON-registration
    of ProposalStatusHistory + ProposalTimelineEvent).
  - **New backend modules:** `backend/extra_work/proposal_state_machine.py`
    (5-entry ALLOWED_TRANSITIONS set, `_user_can_drive_proposal_transition`,
    `apply_proposal_transition`, `emit_proposal_event`,
    `allowed_next_proposal_statuses`, override coercion mirror,
    parent-EW auto-advance bypass); `backend/extra_work/proposal_tickets.py`
    (`spawn_tickets_for_proposal(proposal, *, actor)` — idempotent,
    honours `is_approved_for_spawn`, never copies `internal_note` into
    ticket description); `backend/extra_work/views_proposals.py`
    (7 view classes — ProposalListCreateView / ProposalDetailView /
    ProposalTransitionView / ProposalStatusHistoryView /
    ProposalTimelineView / ProposalLineListCreateView /
    ProposalLineDetailView; per-action provider-only guards mirror
    `_require_provider_pricing_permission`).
  - **New migrations:** `backend/extra_work/migrations/0004_proposal_models.py`
    (creates Proposal, ProposalLine, ProposalStatusHistory,
    ProposalTimelineEvent + the partial UniqueConstraint
    `uniq_proposal_open_per_request` with
    `condition=Q(status__in=["DRAFT", "SENT"])` + 3 indexes);
    `backend/tickets/migrations/0009_ticket_proposal_line.py`
    (cross-app FK on Ticket, depends on `extra_work.0004_proposal_models`).
  - **New tests:** `backend/extra_work/tests/test_sprint28_proposal.py`
    (30 tests across 13 classes — ProposalCRUDTests,
    ProposalSendAdvancesParentTests, CustomerVisibilityTests,
    DualNotePrivacyTests, CustomerApproveSpawnTests, CustomerRejectTests,
    ProviderOverrideTests, AtomicityTests, IdempotencyTests,
    TimelineEmissionTests, ScopeTests, StaffTests,
    ProposalReSendAfterRejectionTests, UniqueOpenProposalTests);
    `backend/extra_work/tests/test_sprint28_proposal_state_machine.py`
    (10 tests across 3 classes — structural allowed-set, role × scope
    matrix, provider-override coercion); `backend/audit/tests/test_sprint28_proposal_audit.py`
    (7 tests across 3 classes — Proposal CRUD audit, ProposalLine CRUD audit,
    H-11 lock asserting zero AuditLog rows for ProposalTimelineEvent +
    ProposalStatusHistory after a full lifecycle run).
- **Migration status:** both migration files created. **Applied to the
  dev DB 2026-05-17** by user after the Batch 8 commit;
  `showmigrations` shows `[X] extra_work.0004_proposal_models` and
  `[X] tickets.0009_ticket_proposal_line`. Test DB auto-applies during
  `manage.py test`.
- **Tests / checks run:**
  - Targeted: `python manage.py test
    extra_work.tests.test_sprint28_proposal
    extra_work.tests.test_sprint28_proposal_state_machine
    audit.tests.test_sprint28_proposal_audit --keepdb -v 1` → **47/47 OK**
    in 15.7s.
  - Broader sweep: `python manage.py test extra_work tickets audit
    customers --keepdb -v 1` → **516/516 OK** in 352.4s.
  - Full backend suite (per backend-engineer report): **994/994 OK**.
  - `manage.py check`: 0 issues. `makemigrations --dry-run --check`:
    No changes detected.
  - No frontend files touched (intentionally — Batch 8 backend-only per
    PM scope verification); no frontend checks run.
- **Important decisions made (also in §9):**
  - **Q1 default applied**: spec names `customer_explanation` +
    `internal_note` on the new `ProposalLine` (legacy
    `ExtraWorkPricingLineItem` keeps its `customer_visible_note` /
    `internal_cost_note` — different concept).
  - **1:N parent→proposals** with partial UniqueConstraint blocking
    parallel open (DRAFT/SENT) rows. Re-send after rejection creates a
    fresh DRAFT row, not a transition on the existing row.
  - **`Ticket.proposal_line` FK** added (Option A from PM Q5a) — parallel
    to Batch 7's `extra_work_request_item` FK, not a reuse. Option B
    (reuse `extra_work_request_item`) was rejected because ProposalLine
    carries divergent (unit_price, quantity, customer_explanation) values.
  - **`apply_proposal_transition` BYPASSES `extra_work.state_machine.
    apply_transition`** for the parent-EW auto-advance on send +
    approve/reject. This avoids the legacy `pricing_line_items_required`
    precondition (which targets `ExtraWorkPricingLineItem`, not the
    new ProposalLine flow). The bypass writes the parent status + a
    fresh `ExtraWorkStatusHistory` row inside the same atomic block.
  - **`Proposal.send` rejects when parent EW is in `REQUESTED`** —
    operator must drive `REQUESTED → UNDER_REVIEW` manually via the
    existing `/transition/` endpoint before sending. HTTP 400 with
    stable code `proposal_send_requires_under_review`.
  - **Provider-driven SENT → CANCELLED is also coerced to
    `is_override=True` + reason required** (provider withdrawing a sent
    proposal — significant act, audit trail must explain).
  - **`is_approved_for_spawn` per-line column added with `default=True`**
    (forward-compat: parked per-line approve/reject UX). Spawn helper
    respects it. No UI flips it in Batch 8.
  - **`customer_visible` flag on `ProposalTimelineEvent`** written at
    emission time. Customer serializer filters on it AND omits
    `metadata` entirely (where the override_reason text would live for
    `ADMIN_OVERRIDDEN` events).
  - **H-11 audit registration**: Proposal + ProposalLine in full-CRUD
    AuditLog; ProposalStatusHistory + ProposalTimelineEvent
    deliberately NOT registered (the history rows ARE the audit trail
    for workflow override). Regression-locked by
    `ProposalTimelineEventNotAuditedTests`.
  - **Reused `osius.ticket.view_building`** for provider building-scope
    checks on every proposal endpoint — no new `osius.*` keys
    introduced (master plan §2 "do not rename osius.*" rule extends to
    "do not invent parallel keys when an existing one expresses the
    same scope").
- **Remaining risks:**
  - **No frontend exposure of the proposal builder yet** — Batch 8 is
    backend-only per master plan §6 (zero frontend bullets). Operators
    cannot compose a proposal via the UI until Batch 9 (EW dashboard)
    or a dedicated frontend batch ships the builder UX.
  - **`Proposal` CREATE writes TWO AuditLog rows** by design (CREATE +
    immediate UPDATE for the `recompute_totals` save). The audit test
    asserts on the CREATE row specifically; future consumers of the
    audit feed should be aware that proposal creation lands as two
    rows. Splitting `recompute_totals` to be inline at create-time
    would diverge from the `ExtraWorkRequest.recompute_totals` pattern
    the brief asked us to mirror; deferred as a polish item.
  - **`CUSTOMER_VIEWED` timeline event is emitted on every customer GET**
    of a SENT proposal — not de-duplicated. PM brief's timeline-emission
    test asserts on CREATED / SENT / CUSTOMER_APPROVED /
    CUSTOMER_REJECTED / ADMIN_OVERRIDDEN counts only so we are in
    compliance; a future batch may want to dedupe per-customer-per-day.
  - **Parent EW `CUSTOMER_REJECTED → UNDER_REVIEW` must be driven
    manually by operator** before a new proposal can be POSTed against
    the same parent (matches `extra_work.state_machine.ALLOWED_TRANSITIONS`).
    Frontend UX should make this step obvious when shipping the
    proposal builder UI.
  - **`Ticket.proposal_line` is `SET_NULL` on ProposalLine delete** —
    audit history of spawn origin is lost if the line is deleted
    post-spawn. Same trade-off as Batch 7's `extra_work_request_item`.
  - **`ExtraWorkRequest` is still NOT registered for audit** — Batch 8
    propagates status changes from proposal transitions onto the
    parent (`status`, `override_*`, `customer_decided_at`) but those
    writes do not land in the generic AuditLog because the parent is
    unregistered. Pre-existing Batch 6 deferral; a future sprint
    registering the parent will need to pick up these propagation
    diffs deliberately.
  - **Dev DB schema applied 2026-05-17** by user via
    `python manage.py migrate extra_work tickets` — proposal endpoints
    exercisable against the dev container.

### Batch 9 — Extra Work dashboard and stats

Goal: dashboard integration for Extra Work. Depends on Batches 5–8 (the
shapes those settle determine the stats payload).

- [x] ~~Add Extra Work stats endpoints: `GET /api/extra-work/stats/` and
      `GET /api/extra-work/stats/by-building/`. Scoped per requesting
      role. Returns totals + by-status + awaiting-customer-approval +
      awaiting-pricing + urgent buckets.~~
- [x] ~~Add Extra Work dashboard cards to
      [`frontend/src/pages/DashboardPage.tsx`](../../frontend/src/pages/DashboardPage.tsx).
      Two top-level sections side by side: Tickets and Extra Work.~~
      (Implementation: the two top-level `<section>` elements are
      wrapped in a `<div className="dashboard-two-col">` container.
      CSS in `frontend/src/index.css` declares `display: grid;
      grid-template-columns: 1fr; gap: 24px;` by default with a
      `@media (min-width: 1400px)` rule promoting to
      `grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      align-items: start;`. The `minmax(0, 1fr)` constraint is
      load-bearing — it prevents the inner Tickets recent-tickets
      table from pushing its column wider than 50% of the viewport.
      At < 1400px both sections stack vertically (mobile / narrow-
      desktop). The 1400px breakpoint is intentionally higher than
      the inner `.dash-grid` breakpoint (1100px) so the Tickets
      section preserves its own `1fr + 340px` split functional
      inside the left column.)
- [x] ~~Make dashboard render different shapes for provider-side vs
      customer-side users. CUSTOMER_USER sees their own buckets; provider
      roles see scoped aggregates.~~ (Backend returns the same JSON
      shape for every role — the *scope* differs, not the *fields*.
      `scope_extra_work_for` returns `.none()` for STAFF, which
      naturally produces a zero-bucket payload; the frontend renders
      an empty-state container when `total === 0 &&
      Object.keys(by_status).length === 0`. CUSTOMER_USER gets visual
      emphasis on the awaiting-customer KPI.)
- [x] ~~Add tests: backend stats endpoint scope + role shape; frontend
      Playwright for the two-section layout.~~

#### Batch 9 completion (2026-05-17)

- **Date:** 2026-05-17.
- **Commit:** uncommitted on working tree as of 2026-05-17, on top of
  `ec66380`.
- **Files changed (7 edits + 2 new files):**
  - **Backend edits:** `backend/extra_work/views.py` (+135 lines —
    `Count`/`Q` imports added; two module-level constants
    `EXTRA_WORK_TERMINAL_STATUSES` and
    `EXTRA_WORK_AWAITING_PRICING_STATUSES`; two new `@action(detail=
    False, methods=["get"])` methods on `ExtraWorkRequestViewSet` —
    `stats` and `stats_by_building`).
  - **Frontend edits:** `frontend/src/api/extraWork.ts` (added typed
    helpers `getExtraWorkStats()` + `getExtraWorkStatsByBuilding()`
    next to existing extra-work helpers — Option A from PM Q2);
    `frontend/src/api/types.ts` (added `ExtraWorkStatusValue` /
    `ExtraWorkRoutingValue` / `ExtraWorkUrgencyValue` string-literal
    unions and `ExtraWorkStats` / `ExtraWorkStatsByBuildingRow` /
    `ExtraWorkStatsByBuildingResponse` interfaces next to the
    existing `TicketStats` types around line 240);
    `frontend/src/pages/DashboardPage.tsx` (additive — new Extra
    Work section after the existing Tickets layout; both top-level
    sections wrapped in a `<div className="dashboard-two-col">`
    that renders them **side by side at viewports ≥ 1400px** and
    stacks them at narrower widths; `<section data-testid=
    "dashboard-tickets-section">` wraps the existing Tickets layout
    untouched; new `<section data-testid="dashboard-extra-work-
    section">` next to it with 5-KPI row Total / Active /
    Awaiting pricing / Awaiting customer / Urgent + by-building card +
    status-breakdown card mirroring Tickets visual structure; empty-
    state container `data-testid="dashboard-extra-work-section-empty"`
    when `total === 0 && Object.keys(by_status).length === 0`;
    CUSTOMER_USER gets emphasis class on `data-testid="dashboard-
    extra-work-kpi-awaiting-customer"`; stats loading merged into
    the existing tickets-stats `useEffect` to avoid a new
    `react-hooks/set-state-in-effect` lint hit — same
    `AUTO_REFRESH_INTERVAL_MS` cadence as tickets);
    `frontend/src/index.css` (+29 lines — new `.dashboard-two-col`
    grid rule with the 1400px `min-width` media query; `minmax(0,
    1fr)` constraint prevents the inner Tickets recent-tickets
    table from pushing its column wider than 50% of viewport;
    `align-items: start` keeps both section tops aligned; nested
    `[data-testid="dashboard-extra-work-section"] { margin-top: 0 }`
    neutralises the section's inline `marginTop: 28` offset in
    the side-by-side layout without touching the JSX);
    `frontend/src/i18n/en/dashboard.json` and `nl/dashboard.json`
    (each +26 keys covering section title/sub, 5 KPI label/meta
    pairs, by-building title/sub + empty + 4 count templates, empty
    section copy, and 6 Extra Work status labels — EN/NL parity
    verified via `diff <(grep ...) <(grep ...)`).
  - **New backend test module:** `backend/extra_work/tests/test_sprint28_extra_work_stats.py`
    (19 tests across 5 classes — `ExtraWorkStatsScopeTests` (5 role
    coverage incl. STAFF zero-row), `ExtraWorkStatsBucketsTests` (8
    bucket-definition tests for total/by_status/by_routing/
    by_urgency/active/awaiting_pricing/awaiting_customer_approval/
    urgent), `ExtraWorkStatsByBuildingTests` (3 — order/skip-zero/
    aggregate-match), `ExtraWorkStatsCrossTenantIsolationTests` (2
    — H-1/H-2 lock for provider + customer-user isolation),
    `ExtraWorkStatsSoftDeletedExcludedTests` (1 — `deleted_at`
    rows excluded from every bucket)).
  - **New Playwright spec:** `frontend/tests/e2e/sprint28_extra_work_dashboard.spec.ts`
    (3 tests — provider sees both sections; CUSTOMER_USER sees
    awaiting-customer KPI emphasis; STAFF sees empty state in
    Extra Work section). Uses existing `loginAs(page, DEMO_USERS.X)`
    helper from `fixtures/login.ts` + `fixtures/demoUsers.ts`.
- **Migration status:** **NONE.** No migration created or needed
  (Batch 9 is pure aggregation over existing columns:
  `extra_work.status`, `extra_work.routing_decision`,
  `extra_work.urgency`, `extra_work.building_id`, `extra_work.deleted_at`).
  `manage.py makemigrations --dry-run --check` → No changes detected.
- **Tests / checks run:**
  - Targeted: `python manage.py test
    extra_work.tests.test_sprint28_extra_work_stats --keepdb -v 1` →
    **19/19 OK** in 4.9s.
  - Broader sweep: `python manage.py test extra_work tickets audit
    customers --keepdb -v 1` → **535/535 OK** in 363.1s — no
    regression (Batch 7 instant-ticket tests intact, Batch 8
    proposal tests intact).
  - `manage.py check`: 0 issues. `makemigrations --dry-run --check`:
    No changes detected.
  - Frontend per the frontend-engineer agent's environment:
    `tsc --noEmit -p tsconfig.app.json` → **EXIT=0 clean (strict
    mode)**; `eslint .` → **52 problems = baseline** (zero new hits
    in changed files — the new Extra Work loader was merged into
    the existing tickets-stats effect to avoid a new
    `react-hooks/set-state-in-effect` hit). `vite build` failed
    environmentally in the agent's sandbox (Node 20.18 < required
    20.19 + rolldown UNC binding lookup issue) — typecheck is the
    Tier-1 gate per CLAUDE.md frontend section and is clean; CI
    builds cleanly on Linux runner.
  - From the parent session I could NOT independently re-run the
    frontend gates due to the WSL/UNC bash-tool gotcha (cmd.exe
    refuses UNC paths); typecheck/lint validation is the agent's
    report. CI will confirm on push.
  - Playwright spec **written but NOT executed locally** (WSL
    `frontend/test-results/` root-ownership gotcha; CI exercises
    the 3 cases).
- **Important decisions made (also in §9):**
  - **Responsive two-column dashboard layout shipped.** The two
    top-level `<section>`s are siblings of a `<div className=
    "dashboard-two-col">` wrapper. CSS Grid renders them
    side-by-side at viewports ≥ 1400px (`grid-template-columns:
    minmax(0, 1fr) minmax(0, 1fr)`) and stacked at narrower
    widths (`grid-template-columns: 1fr`). Breakpoint at 1400px
    rather than 1100px so the Tickets section's inner `1fr +
    340px` `dash-grid` split (which itself collapses at 1100px)
    keeps room to breathe inside the half-viewport column.
    `minmax(0, 1fr)` is load-bearing — the inner recent-tickets
    table cannot overflow the column; existing table `overflow-x`
    semantics handle horizontal scroll within the column. No
    JSX content edits inside either section. Existing Tickets
    functionality (KPIs, filters, recent-tickets table, mobile
    cards, pagination, status breakdown, focus list, by-building
    card) unchanged.
  - **Backend returns identical JSON shape for every role** —
    `scope_extra_work_for` is the single source of role
    branching; frontend decides cell emphasis. STAFF gets all-
    zeros naturally because `scope_extra_work_for` returns
    `.none()`. No backend role branching.
  - **`awaiting_customer_approval` defined as `status ==
    PRICING_PROPOSED` only** (Option A from PM Q2). Batch 8's
    `apply_proposal_transition` auto-advance contract makes parent
    EW status the single source of truth for "customer must
    decide" state; OR-ing in `proposals__status=SENT` would have
    double-counted across the JOIN.
  - **`awaiting_pricing` definition**: `routing_decision="PROPOSAL"`
    AND `status IN (REQUESTED, UNDER_REVIEW)` — the operator
    action queue.
  - **Two module-level constants** (`EXTRA_WORK_TERMINAL_STATUSES`,
    `EXTRA_WORK_AWAITING_PRICING_STATUSES`) in `extra_work/views.py`
    shared between both new actions to keep the bucket semantics
    in one place.
  - **Status labels added to `dashboard.json`** under
    `extra_work_status_*` keys (local to this namespace) rather
    than centralised in `common.json`. Avoids a cross-namespace
    refactor in Batch 9; later polish can consolidate.
  - **`data-testid` attributes** locked the Playwright contract:
    `dashboard-tickets-section`, `dashboard-extra-work-section`,
    `dashboard-extra-work-kpi-awaiting-customer`,
    `dashboard-extra-work-section-empty`.
  - **API helper Option A** — typed `getExtraWorkStats()` /
    `getExtraWorkStatsByBuilding()` in
    `frontend/src/api/extraWork.ts` rather than inline `api.get<>`
    calls — keeps the page free of URL string literals + matches
    the existing extra-work helper pattern.
- **Remaining risks:**
  - **At viewports < 1400px the sections stack vertically** — by
    design (responsive default). Most laptop screens are
    1366×768 / 1440×900; users on a 1366px screen will see
    stacked sections, users on a 1440px+ external monitor see
    side-by-side. The 1400px breakpoint can be lowered to
    1280px or 1200px in a future polish batch if stakeholders
    want a wider side-by-side range, but lowering further would
    cramp the Tickets inner `1fr + 340px` split.
  - **Frontend gates not independently re-run from the parent
    session** — typecheck + lint passed in the frontend agent's
    environment (52 problems = baseline; tsc EXIT=0); the WSL/UNC
    cmd.exe gotcha blocked the parent session from reproducing.
    CI will confirm on push.
  - **`vite build` not run locally** (agent environment had a
    Node-version + rolldown native-binding mismatch unrelated to
    Batch 9 code). Build is exercised on CI.
  - **Auto-refresh effect merged with existing tickets-stats
    effect** to avoid a new `react-hooks/set-state-in-effect` lint
    hit (the existing tickets-stats effect already trips this
    rule and is baseline; the new loaders were added to it rather
    than into a fresh effect that would introduce a new rule
    violation). Behaviour identical — same
    `AUTO_REFRESH_INTERVAL_MS`, same cleanup.
  - **Status-breakdown card** rendered (mirrors existing Tickets
    `section_status_title` block for visual symmetry). The PM
    brief noted this was optional; the frontend agent kept it for
    symmetry.
  - **Playwright spec not executed locally** — WSL root-owned
    `frontend/test-results/` gotcha; CI exercises.

### Batch 10 — Staff per-building granularity

Goal: enable the B1/B2/B3 example per spec §B.4 / product rule #6.

- [x] ~~Extend `BuildingStaffVisibility` (or equivalent) with a per-row
      permission level.~~ Implemented as `BuildingStaffVisibility.VisibilityLevel`
      TextChoices enum (`ASSIGNED_ONLY` / `BUILDING_READ` /
      `BUILDING_READ_AND_ASSIGN`) and `visibility_level` CharField. Per
      §10 Q2 default: migration + model `default=BUILDING_READ` to
      preserve existing B2 behaviour (the old code already granted
      full-building read via every BSV row; defaulting to
      ASSIGNED_ONLY would have downgraded every seed/test).
- [x] ~~Support the spec example: B1 own assigned only; B2 all building
      tickets but cannot assign; B3 all building tickets and can assign.~~
- [x] ~~Update backend scoping at `backend/accounts/scoping.py` STAFF
      branch.~~ Only BSV rows with `visibility_level IN
      (BUILDING_READ, BUILDING_READ_AND_ASSIGN)` contribute building-
      wide visibility; ASSIGNED_ONLY rows recognise the STAFF user at
      the building (for direct-assignment-target eligibility via
      `_validate_target_staff`) but do NOT widen visibility. H-4
      floor (`Q(_assigned=True)` branch) preserved untouched.
- [x] ~~Update assignment gate in `backend/tickets/views.py` `assign`
      action.~~ STAFF allowed iff an active BSV row exists for the
      ticket's building with `visibility_level=BUILDING_READ_AND_ASSIGN`;
      non-STAFF/non-provider-admin rejected. `TicketAssignSerializer.
      validate` mirror-widened (necessary deviation — the existing
      Sprint 28 Batch 2 serializer gate was rejecting all STAFF before
      view code could run; both layers now enforce the same B3 rule).
      `views_staff_assignments.py::_gate_actor` deliberately
      UNCHANGED (PM Q5) — the multi-staff M:N `TicketStaffAssignment`
      remains a provider-admin-only orchestration surface; B3 maps
      to the BM-assign verb, not to the multi-staff M:N.
- [x] ~~Add new `osius.*` keys, or rely on the model field directly.~~
      **Model field is enough** (PM Q6). NO new `osius.*` keys added.
      Avoids fragmenting the permission vocabulary and resolver
      surface; `BuildingStaffVisibility.visibility_level` is the
      single source of truth, checked directly in scope helper and
      view gates.
- [x] ~~Update frontend staff permission UI on `UserFormPage.tsx` with
      the per-building level selector.~~ Smallest-safe addition inside
      the existing `StaffDetailsSection` BSV editor — new column /
      mobile-row dropdown with three options, `data-testid="staff-
      visibility-level-select-{buildingId}"`. No redesign. PATCH
      payload extended via `StaffVisibilityPatch` to send only the
      mutated field (so toggling can_request_assignment doesn't
      clobber visibility_level and vice versa).
- [x] ~~When a Staff user can see all tickets in a building, ensure
      tickets assigned to them are visually prioritised in the list UI
      (sort first or marked differently).~~ Implemented as a
      conditional "Assigned to you" badge on the dashboard ticket
      table rows (desktop + mobile card) when `userRole === "STAFF"
      && ticket.assigned_to === me.id`. Sort-first parked as
      remaining UX debt (would require role-gated shared-list
      reordering — non-trivial in this batch). Badge testids:
      `ticket-row-assigned-to-you`, `ticket-card-assigned-to-you`.
- [x] ~~Add tests: backend scope tests for B1/B2/B3 shapes; frontend
      Playwright for the per-row selector.~~ 19 new backend tests
      across 9 classes + 1 audit-side test for `visibility_level`
      UPDATE diff; 1 new Playwright spec with 2 cases (selector
      renders + exactly three options).

#### Batch 10 completion (2026-05-17)

- **Date:** 2026-05-17.
- **Commit:** uncommitted on working tree as of 2026-05-17, on top of
  `eb689a1`.
- **Files changed (9 edits + 4 new files):**
  - **Backend edits:**
    - `backend/buildings/models.py` (+48 / VisibilityLevel TextChoices
      + `visibility_level` CharField + class docstring update).
    - `backend/accounts/scoping.py` (+24 / STAFF branch filters BSV
      rows to BUILDING_READ-or-above; `building_ids_for` STAFF branch
      keeps returning all BSV building_ids regardless of level —
      documented asymmetry).
    - `backend/tickets/views.py` (+24 / `assign` action: STAFF
      allowed iff B3 BSV row exists for ticket.building; non-STAFF
      provider gate unchanged).
    - `backend/tickets/serializers.py` (+22 / `TicketAssignSerializer.
      validate` mirror-widened — necessary deviation: the existing
      Sprint 28 Batch 2 serializer gate was rejecting all STAFF
      before view code could fire; both layers now share the same
      B3 BSV-level check; the deeper serializer audit row 26 stays
      open as a follow-up).
    - `backend/accounts/serializers_staff.py` (+22 / `visibility_level`
      added to read + update BSV serializer Meta.fields; DRF derives
      ChoiceField from the model enum).
    - `backend/audit/signals.py` (+5 / `_BSV_TRACKED_FIELDS` extended
      from `("can_request_assignment",)` to
      `("can_request_assignment", "visibility_level")`; existing
      UPDATE handler iterates the tuple — no new handler needed).
  - **Frontend edits:**
    - `frontend/src/api/types.ts` (+23 / `StaffVisibilityLevel`
      string-literal union + `visibility_level` field on
      `BuildingStaffVisibilityAdmin`; comment locks "do NOT pre-
      filter the building dropdown by level on the client").
    - `frontend/src/api/admin.ts` (+13 / `updateStaffVisibility`
      now takes a `StaffVisibilityPatch` object so concurrent
      edits to `can_request_assignment` vs `visibility_level`
      don't clobber each other).
    - `frontend/src/pages/admin/UserFormPage.tsx` (+97 / new
      per-row dropdown in desktop table + mobile card BSV editor;
      new `handleChangeVisibilityLevel`; existing
      `handleToggleCanRequest` adapted to the new patch shape;
      no redesign of surrounding form).
    - `frontend/src/pages/DashboardPage.tsx` (+36 / conditional
      "Assigned to you" badge on STAFF rows where
      `ticket.assigned_to === me.id`; desktop subject cell + phone-
      width ticket card; uses existing `useAuth().me` + i18n key).
    - `frontend/src/i18n/en/common.json` (+5 / `staff_admin.level_*`
      + `tickets.assigned_to_you`).
    - `frontend/src/i18n/nl/common.json` (+5 / NL parity).
  - **Docs edits:**
    - `docs/architecture/sprint-27-rbac-matrix.md` (+56 / §1.2 BSV
      row mentions visibility_level; §3 H-4 paragraph references
      the new `StaffH4FloorTests`; new §14 Test footprint section
      for Batch 10 delta).
    - `docs/audits/current-state-2026-05-16-system-audit.md` (+4 /
      row 17 status flipped to OK + Batch 10 reference; row 26
      noted as PARTIAL with view-layer half closed).
  - **New backend modules / tests:**
    - `backend/buildings/migrations/0003_buildingstaffvisibility_visibility_level.py`
      (single AddField op, default `"BUILDING_READ"`; backfills
      existing rows automatically).
    - `backend/tickets/tests/test_sprint28_staff_building_granularity.py`
      (19 tests / 9 classes: default, B1 ASSIGNED_ONLY scope, B2
      BUILDING_READ scope + assign block, B3 BUILDING_READ_AND_ASSIGN
      scope + assign happy path + audit-pipeline non-regression,
      cross-building isolation, cross-company isolation, target-
      validation unchanged, H-4 floor, multi-staff endpoint still
      admin-only).
    - `backend/audit/tests/test_sprint28_visibility_level_audit.py`
      (1 test pinning UPDATE-row shape for `visibility_level`).
  - **New frontend tests:**
    - `frontend/tests/e2e/staff-building-granularity.spec.ts`
      (2 cases — dropdown renders for Ahmet via SUPER_ADMIN; three
      options exist).
- **Migration status:** `buildings/0003_buildingstaffvisibility_visibility_level`
  created. **NOT applied to the dev DB in this pass** — user to
  approve before applying. The test DB auto-applies via `manage.py
  test --keepdb`.
- **Tests / checks run:**
  - Targeted: `python manage.py test
    tickets.tests.test_sprint28_staff_building_granularity
    audit.tests.test_sprint28_visibility_level_audit --keepdb -v 1` →
    **19/19 OK** in 5.1s. (Backend agent's environment: full suite
    `python manage.py test --keepdb -v 1` → **1032/1032 OK**.)
  - Broader sweep: `python manage.py test accounts tickets audit
    customers --keepdb -v 1` → **585/585 OK** in 471.9s — no
    regression to existing Sprint 24-28 STAFF tests (the
    `default=BUILDING_READ` preserves their assumptions).
  - `manage.py check`: 0 issues. `makemigrations --dry-run --check`:
    No changes detected (after the migration file landed).
  - Frontend gates from agent environment: `tsc --noEmit -p
    tsconfig.app.json` → EXIT=0 clean; `eslint .` → **52 problems =
    baseline** (zero new hits in changed files — 6 pre-existing
    `react-hooks/set-state-in-effect` warnings sit in
    untouched `useEffect` bodies). `vite build` **failed
    environmentally** (rolldown `win32-x64-msvc` native binding
    not installed in WSL — same class of WSL/UNC limitation as the
    documented `'tsc' is not recognized` cmd.exe issue from prior
    batches). CI's Linux runner builds cleanly.
  - Playwright spec **written but NOT executed locally** (WSL
    `frontend/test-results/` root-ownership gotcha; CI exercises).
- **Important decisions made (also in §9):**
  - **Migration + model `default=BUILDING_READ`** (PM Q2) — preserves
    existing B2 behaviour for every existing BSV row + every Sprint
    24-28 staff test that creates a BSV row expecting building-wide
    read.
  - **B1 ASSIGNED_ONLY is a NEW per-row downgrade semantic** (PM
    Q3). Before Batch 10: BSV row → automatic B2. After Batch 10:
    BSV row with ASSIGNED_ONLY → recognised at building (for
    direct-assignment-target eligibility) but does NOT widen
    visibility beyond `TicketStaffAssignment`.
  - **H-4 invariant floor preserved structurally** — the
    `Q(_assigned=True)` branch in `scope_tickets_for` STAFF branch
    is untouched. STAFF with TicketStaffAssignment ALWAYS sees the
    assigned ticket regardless of `visibility_level` value (or even
    absence of a BSV row). Locked by new `StaffH4FloorTests` —
    closes the doc-drift noted in audit row 25.
  - **Model field is the source of truth — NO new `osius.*` keys**
    (PM Q6). Avoids fragmenting permission vocabulary.
  - **Multi-staff M:N (`TicketStaffAssignment`) endpoint stays
    admin-only** (PM Q5). B3 maps to the BM-assign verb only;
    `views_staff_assignments::_gate_actor` unchanged. Locked by
    `StaffStaffAssignmentsEndpointUnchangedForStaffTests`.
  - **`TicketAssignSerializer.validate` mirror-widening was
    necessary** (backend agent flagged deviation). The Sprint 28
    Batch 2 serializer gate was rejecting all STAFF before the
    view-layer change could ever reach `save()`. Keeping the brief
    literal would have made the B3 → 200 path impossible. Both
    layers now share the same BSV-level check (defence in depth).
  - **`building_ids_for(STAFF)` asymmetry preserved** — ASSIGNED_ONLY
    STAFF still see the building in dropdowns (so they remain a
    valid direct-assignment target) but do NOT see other tickets
    there. Documented in the helper's docstring.
  - **`updateStaffVisibility` API helper refactored to take a
    `StaffVisibilityPatch` object** — avoids clobbering one field
    when only the other is being mutated.
  - **"Assigned to you" badge implemented (not sort-first)** — the
    badge is the smallest-safe surface; sort-first would require
    role-gated reordering of a shared list. Sort-first parked as
    remaining UX debt.
- **Remaining risks:**
  - **Dev DB schema BEHIND code** until user approves
    `python manage.py migrate buildings` — the `visibility_level`
    column on `buildings_buildingstaffvisibility` will not exist
    in the dev container until applied. `accounts/scoping.py`
    will raise `column does not exist` errors against the dev DB
    until the migration is applied.
  - **`vite build` not independently re-run from the parent
    session** — rolldown `win32-x64-msvc` native binding
    unresolvable through the WSL UNC bridge. Same class of
    environmental limitation as prior batches. Typecheck (Tier 1
    per CLAUDE.md) was independently verified; CI exercises the
    full build pipeline.
  - **Sort-first prioritisation for own-assigned tickets parked**
    as remaining UX debt — badge ships; sort would require role-
    gated shared-list reordering.
  - **`TicketAssignSerializer.validate` deep audit (audit row
    26) remains open** — Batch 10 widened the gate; a formal
    boolean-edge-case audit of the serializer is a follow-up.
  - **M:N `TicketStaffAssignment` check not honoured by the badge**
    — the badge fires only on `ticket.assigned_to === me.id`
    (legacy single-assignee FK). The M:N check would need a
    per-row staff-assignments fetch and was deferred as out of
    "smallest-safe" scope.
  - **Frontend M:N PATCH races**: extending `updateStaffVisibility`
    to a `StaffVisibilityPatch` object solved the field-clobber
    concern; no further race-condition risk introduced.

### Batch 11 — Staff completion routing

Goal: configurable per-staff / per-building routing per product rule #7.

- [x] ~~Add a Staff "I completed my work" flow. STAFF can drive a new
      transition out of `IN_PROGRESS`.~~
- [x] ~~Require completion note on every Staff completion (already a Sprint
      25C invariant for `IN_PROGRESS → WAITING_CUSTOMER_APPROVAL` —
      extend to the new Staff path).~~
- [x] ~~Support optional completion attachment/photo. Reuse the existing
      `TicketAttachment` model + `is_hidden=False` for the visible-evidence
      semantic.~~ (Inline attachment uploader inside the modal parked as
      remaining UX debt; modal copy directs operator to the existing
      Attachments card on the page before submitting. Backend's
      `completion_evidence_required` rule accepts either note OR visible
      attachment, so the note-only modal still satisfies the rule.)
- [x] ~~Default route: Staff marks done → `WAITING_MANAGER_REVIEW` (new
      ticket status), then Building Manager accepts to
      `WAITING_CUSTOMER_APPROVAL` or rejects back to `IN_PROGRESS`.
      Per §10 open question 2 default.~~ (BM rejection requires a note;
      enforced at both serializer + state-machine layer.)
- [x] ~~Optional configured route: when the configurable flag is enabled,
      Staff marks done → directly to `WAITING_CUSTOMER_APPROVAL`. Flag
      lives on `BuildingStaffVisibility` or `StaffProfile` — sprint
      design decides.~~ Implemented as
      `BuildingStaffVisibility.staff_completion_routes_to_customer:
      BooleanField(default=False)` — per-staff-per-building flag matches
      product rule #7. PM Q2 chose BSV over StaffProfile for the
      per-building granularity.
- [x] ~~Keep Ticket and Extra Work routing configurations **separate** (per
      product rule #7).~~ Extra Work staff completion is parked because
      STAFF has no EW scope today (G-B7 — `scope_extra_work_for` returns
      `.none()`). Future batch can add the EW equivalent without
      collision: the BSV flag is Ticket-scoped by name, leaving room
      for a parallel `staff_completion_routes_to_customer_extra_work`
      column.
- [x] ~~Update `ALLOWED_TRANSITIONS` in
      [`backend/tickets/state_machine.py:53-92`](../../backend/tickets/state_machine.py#L53-L92)
      with the new STAFF entries. Update matrix doc H-5 row to reflect
      the structurally-permitted STAFF transitions.~~ Four new entries:
      `(IN_PROGRESS, WAITING_MANAGER_REVIEW)` with STAFF row;
      `(IN_PROGRESS, WAITING_CUSTOMER_APPROVAL)` extended with STAFF row
      (gated by routing-flag check in `apply_transition`);
      `(WAITING_MANAGER_REVIEW, WAITING_CUSTOMER_APPROVAL)` (BM accepts);
      `(WAITING_MANAGER_REVIEW, IN_PROGRESS)` (BM rejects).
      New scope `SCOPE_STAFF_ASSIGNED` (TicketStaffAssignment membership).
      Matrix H-5 row clarified — STAFF-marks-own-work-done is NOT
      approving-customer-completion.
- [x] ~~Frontend completion modal for STAFF — completion note required +
      optional attachment + routing-aware destination text.~~
- [x] ~~Add tests: structural tests on the new transitions; configured-
      routing-flag tests; completion-evidence regression tests; matrix
      H-5 safety net update.~~ 34 new backend tests across 11 classes;
      Playwright spec written (not executed locally).

#### Batch 11 completion (2026-05-17)

- **Date:** 2026-05-17.
- **Commit:** uncommitted on working tree as of 2026-05-17, on top of
  `3d91810`.
- **Files changed (15 edits + 5 new files):**
  - **Backend edits (7):**
    - `backend/tickets/models.py` (+13 — new `TicketStatus.WAITING_MANAGER_REVIEW`
      enum value + new `Ticket.manager_review_at: DateTimeField(null=True,
      blank=True)` timestamp column).
    - `backend/buildings/models.py` (+23 — new
      `BuildingStaffVisibility.staff_completion_routes_to_customer: BooleanField(default=False)`
      flag + docstring extension).
    - `backend/tickets/state_machine.py` (+108 — `SCOPE_STAFF_ASSIGNED`
      constant + branch in `_user_passes_scope`; 4 new ALLOWED_TRANSITIONS
      entries (1 NEW + 1 EXTENDED + 2 NEW for WAITING_MANAGER_REVIEW);
      `TIMESTAMP_ON_ENTER` extension for `manager_review_at`;
      `COMPLETION_EVIDENCE_TRANSITIONS` extended to include `(IN_PROGRESS,
      WAITING_MANAGER_REVIEW)`; STAFF routing-flag check + BM rejection-
      note check in `apply_transition` (both with stable codes
      `staff_completion_route_mismatch` + `rejection_note_required`)).
    - `backend/tickets/serializers.py` (+38 — BM rejection-note rule in
      `TicketStatusChangeSerializer.validate`; `is_assigned_staff`
      SerializerMethodField + `manager_review_at` field on
      `TicketDetailSerializer`).
    - `backend/tickets/views.py` (+68 — new
      `@action(detail=True, methods=["get"], url_path="staff-completion-route")`
      on `TicketViewSet`; STAFF must have `TicketStaffAssignment` + ticket
      in IN_PROGRESS; provider operators in scope; out-of-scope 404).
    - `backend/accounts/serializers_staff.py` (+11 — adds
      `staff_completion_routes_to_customer` to BSV read + update
      Meta.fields so admin PATCHes mutate the new field; necessary
      extension surface mirroring Batch 10's `visibility_level` rollout).
    - `backend/audit/signals.py` (+10 — `_BSV_TRACKED_FIELDS` extended
      from `("can_request_assignment", "visibility_level")` to include
      `"staff_completion_routes_to_customer"`).
  - **Frontend edits (6):**
    - `frontend/src/api/types.ts` (+37 — `WAITING_MANAGER_REVIEW` added
      to `TicketStatus` union; `manager_review_at` + `is_assigned_staff`
      added to `TicketDetail`; `StaffVisibilityLevel`-style
      `StaffCompletionRoute` + `StaffCompletionRouteResponse` types;
      `BuildingStaffVisibilityAdmin.staff_completion_routes_to_customer`
      added).
    - `frontend/src/api/admin.ts` (+25 — `StaffVisibilityPatch` extended;
      new `getStaffCompletionRoute(ticketId)` helper).
    - `frontend/src/pages/TicketDetailPage.tsx` (+279 — STAFF
      "Complete work" button gated on `STAFF + IN_PROGRESS + is_assigned_staff`;
      inline-card modal mirroring the Sprint 27F-F1 override modal shape
      (rather than a floating overlay) with required note textarea +
      attachment hint + routing-aware destination text fetched from
      the new endpoint + routing-aware submit-button label; handlers
      for `completion_evidence_required` (inline error) +
      `staff_completion_route_mismatch` (refetch route + retry).
      Testids: `ticket-staff-complete-button`, `ticket-staff-complete-modal`,
      `ticket-staff-complete-route`, `ticket-staff-complete-note`,
      `ticket-staff-complete-error`, `ticket-staff-complete-cancel`,
      `ticket-staff-complete-submit`).
    - `frontend/src/pages/admin/UserFormPage.tsx` (+97 — new
      "Completion routes directly to customer" checkbox stacked under
      the existing `can_request_assignment` checkbox in the BSV admin
      editor (desktop column + mobile card mirror); testids
      `staff-completion-routes-to-customer-{buildingId}` +
      `staff-completion-routes-to-customer-mobile-{buildingId}`).
    - `frontend/src/i18n/en/common.json` (+22 — 17 Batch 11 keys
      covering modal copy, routing destination strings, submit labels,
      error messages, attachment hint, status label
      `ticket_status.waiting_manager_review`, admin checkbox label).
    - `frontend/src/i18n/nl/common.json` (+22 — NL parity).
  - **New backend modules / tests (4):**
    - `backend/tickets/migrations/0010_waiting_manager_review.py` —
      `AlterField` on `Ticket.status` (regenerates `choices`) +
      `AddField` for `manager_review_at`.
    - `backend/buildings/migrations/0004_bsv_staff_completion_routes_to_customer.py`
      — `AddField` for the new BSV boolean (`default=False`; preserves
      pre-Batch-11 behaviour).
    - `backend/tickets/tests/test_sprint28_staff_completion.py` —
      31 tests across 10 classes (structural transitions; default route;
      configured route; completion evidence × 4 sub-cases × 2 routes;
      route mismatch; STAFF-not-assigned forbidden; H-5 STAFF-cannot-
      approve lock; BM accepts; BM rejects with + without note; new
      endpoint authorization matrix).
    - `backend/audit/tests/test_sprint28_staff_completion_route_audit.py`
      — 3 tests (PATCH flag emits AuditLog UPDATE row; combined PATCH
      with visibility_level emits ONE row with both diffs; unrelated
      field PATCH does not include the flag in the diff).
  - **New frontend tests (1):**
    - `frontend/tests/e2e/staff-completion-routing.spec.ts` — 2 cases
      (STAFF completion modal flow + admin checkbox toggle and
      persistence).
  - **Docs edits (2):**
    - `docs/architecture/sprint-27-rbac-matrix.md` (+69 — H-5 row
      clarified with STAFF-marks-own-work-done vs customer-decision
      distinction + Batch 11 test references; new §15 Test footprint
      section).
    - `docs/audits/current-state-2026-05-16-system-audit.md` (+2 —
      row 18 status flipped to OK with Sprint 28 Batch 11 reference).
- **Migration status:** **Both migrations created, NOT applied to dev
  DB in this pass** — user to approve before applying. NOTE: Batch 10
  migration `buildings/0003_buildingstaffvisibility_visibility_level`
  is also still NOT applied to dev DB (user committed Batch 10 without
  approving migrate). When you approve, the migrate command must apply
  both `buildings/0003` AND `buildings/0004` AND `tickets/0010` in
  order. Test DB auto-applies during `manage.py test --keepdb`.
- **Tests / checks run:**
  - Targeted: `python manage.py test
    tickets.tests.test_sprint28_staff_completion
    audit.tests.test_sprint28_staff_completion_route_audit
    --keepdb -v 1` → **34/34 OK** in 8.0s.
  - Backend agent's environment broader sweep (`accounts tickets audit
    customers buildings`): **644/644 OK** in 515.5s.
  - Re-verified targeted from parent session: **34/34 OK** in 8.0s.
    Broader sweep re-run from parent session (`accounts tickets audit
    customers buildings`): **644/644 OK** in 719.7s — no regression
    confirmed independently.
  - `manage.py check`: 0 issues. `makemigrations --dry-run --check`:
    No changes detected.
  - Frontend gates from agent environment: `tsc --noEmit -p
    tsconfig.app.json` → clean (no errors); `vite build` → clean,
    619ms, 2789 modules transformed; `eslint .` → **52 problems =
    baseline** (zero new hits in changed files; the 7 hits inside
    `TicketDetailPage.tsx` + `UserFormPage.tsx` are pre-existing
    `react-hooks/set-state-in-effect` warnings on untouched useEffect
    blocks). Parent session cannot independently re-verify (WSL/UNC
    cmd.exe gotcha — `'tsc' is not recognized`); CI will confirm.
  - Playwright spec **written but NOT executed locally** (WSL
    `frontend/test-results/` root-ownership gotcha; CI exercises).
- **Important decisions made (also in §9):**
  - **`WAITING_MANAGER_REVIEW` is the new TicketStatus value** per
    §6 Batch 11 + §10 Q2 explicit default. Migration regenerates
    `choices` via `AlterField` (no column type change; existing rows
    unaffected).
  - **Routing flag = `BuildingStaffVisibility.staff_completion_routes_to_customer`
    (per-staff-per-building, default False)** per PM Q2. Matches
    product rule #7's "per staff/building, separately for Tickets vs
    Extra Work". Default False preserves the manager-review default.
  - **STAFF completion ALWAYS goes through `apply_transition`** — no
    bypass. The new routing-flag check sits next to the existing
    Sprint 27F-B1 override-coercion + Sprint 25C completion-evidence
    preconditions, same architectural layer. Scope helper stays pure
    (TicketStaffAssignment membership only).
  - **BM rejection of staff completion requires a note** — two-layer
    defence (serializer 400 + state-machine `TransitionError(code=
    "rejection_note_required")`). Programmatic callers cannot bypass.
  - **`(IN_PROGRESS, WAITING_CUSTOMER_APPROVAL)` was EXTENDED with a
    STAFF row** (not duplicated). The flag-state check filters which
    of the two new STAFF-permitted transitions is reachable at
    runtime via the route mismatch error.
  - **`SCOPE_STAFF_ASSIGNED` new scope helper** — STAFF must be in
    `TicketStaffAssignment`. No osius.* key (model-field + scope
    check pattern mirroring Batch 10).
  - **New endpoint `GET /api/tickets/<id>/staff-completion-route/`** —
    smallest auditable shape for frontend route discovery. STAFF
    without assignment → 404; CUSTOMER_USER → 404; provider operators
    in scope get the conservative `"manager_review"` default without
    `?staff_id`, or the resolved route with `?staff_id=<id>`.
  - **`is_assigned_staff: boolean` added to TicketDetailSerializer** —
    frontend uses this directly to decide whether to render the
    "Complete work" button; no separate API call needed on render.
  - **Completion modal is an inline card mirroring the Sprint 27F-F1
    override modal shape** (NOT a floating overlay) — consistent with
    the page's existing modal pattern.
  - **Audit registration via existing `_BSV_TRACKED_FIELDS` tuple
    extension** — one line; existing UPDATE-diff handler covers.
  - **H-5 matrix wording updated** to clarify "STAFF cannot drive
    `WAITING_CUSTOMER_APPROVAL → APPROVED/REJECTED`" (the
    customer-decision); the new Batch 11 STAFF transitions are
    "STAFF marking own work done" — structurally distinct from
    "approving customer completion" which remains forbidden.
- **Remaining risks:**
  - **Dev DB schema BEHIND code** until user approves migration. **TWO
    pending migrations now**: `buildings/0003` (Batch 10 — not yet
    applied) AND `buildings/0004` + `tickets/0010` (Batch 11). User
    must run `python manage.py migrate buildings tickets` to catch
    up. Endpoints touching `WAITING_MANAGER_REVIEW`, `manager_review_at`,
    or BSV.staff_completion_routes_to_customer will raise database
    errors against the dev container until applied.
  - **Inline attachment upload in the completion modal is UX debt** —
    deferred per PM Q12 + backend-engineer report. Modal directs
    operator to the existing Attachments card on the page. Backend's
    `completion_evidence_required` rule still accepts note-only
    completions so the experience is functional.
  - **Frontend gates not independently re-runnable from parent
    session** — same WSL/UNC cmd.exe limitation as prior batches.
    Backend-engineer + frontend-engineer environments both verified
    green. CI will confirm on push.
  - **EW staff completion routing UNIMPLEMENTED** — parked because
    STAFF has no EW scope today (G-B7). Future batch can add a
    parallel `staff_completion_routes_to_customer_extra_work`
    column to the BSV row without collision. The current Batch 11
    flag is intentionally Ticket-only (named for clarity).
  - **`change_status` view was not touched** — STAFF passes
    `is_staff_role(...)` gate (Sprint 23A widened); reaches the
    serializer + state machine where the new logic enforces routing
    and evidence. View-layer change not needed.
  - **Provider on-behalf completion** (admin/BM completing work
    themselves while ticket is IN_PROGRESS) — backend supports it
    via ALLOWED_TRANSITIONS rows (SUPER_ADMIN / COMPANY_ADMIN /
    BUILDING_MANAGER are listed alongside STAFF); the frontend
    does NOT expose a dedicated UI surface for it (admins use the
    generic status-change). Acceptable for Batch 11 scope.
  - **Frontend Playwright spec resolves status via API** (not by
    asserting locale badge text) to keep the test resilient against
    future i18n copy changes. Light testid-based assertions only.

### Batch 12 — Building Manager read-only customer/contact view

Goal: Building Manager surfaces customers and contacts in their assigned
buildings, read-only. Depends on Batch 3 + Batch 4.

- [x] ~~Building Manager sees customers in assigned buildings — list +
      detail view, read-only.~~
- [x] ~~Building Manager sees contacts for those customers — list + detail
      view, read-only.~~
- [x] ~~Read-only by default. No edit affordances on these surfaces.~~
- [x] ~~No global provider settings access. Building Manager cannot reach
      `/admin/companies`, `/admin/buildings` (master list), or settings
      pages.~~ (Playwright spec asserts BM hitting these paths gets
      bounced to `/?admin_required=ok` by `AdminRoute`.)
- [x] ~~Reuse existing scope helpers — no new backend gates needed; the
      backend already scopes via `building_ids_for(user)`.~~
      (Customer reads already worked for BM via `scope_customers_for`;
      Batch 12 added ONE small permission class
      `IsSuperAdminOrCompanyAdminOrBuildingManagerReadCustomer` for
      the contacts views — the brief acknowledged this as the
      Batch 4 deferral. No new `osius.*` keys.)
- [x] ~~Add tests: backend scope tests + frontend Playwright for the
      read-only assertion (no Edit buttons rendered).~~

#### Batch 12 completion (2026-05-18)

- **Date:** 2026-05-18.
- **Commit:** uncommitted on working tree as of 2026-05-18, on top of
  `48bead6`.
- **Files changed (7 edits + 6 new files):**
  - **Backend edits:**
    - `backend/accounts/permissions.py` (+89 — new
      `IsSuperAdminOrCompanyAdminOrBuildingManagerReadCustomer`
      permission class admitting BM on safe methods only when the
      customer is in `scope_customers_for(user)`; falls through to
      the existing `IsSuperAdminOrCompanyAdminForCompany` behaviour
      for unsafe methods / admin roles).
    - `backend/customers/views_contacts.py` (+~10 — swap the
      `permission_classes` on `CustomerContactListCreateView` and
      `CustomerContactDetailView` from
      `IsSuperAdminOrCompanyAdminForCompany` to the new gate; module
      docstring updated to document the Batch 12 widening).
    - `backend/customers/tests/test_sprint28_contacts.py` (+~17 —
      Batch 4 regression-lock test renamed
      `test_building_manager_blocked_on_every_endpoint` →
      `test_building_manager_blocked_on_write_endpoints`; body now
      asserts BM=200 on GET list/detail in scope AND BM=403 on
      POST/PATCH/DELETE; the read-side behaviour is locked in the new
      `test_sprint28_bm_readonly.py` module).
  - **Frontend edits:**
    - `frontend/src/App.tsx` (+ — new imports +
      `CustomerReadRoute` wrapper around `/admin/customers`,
      `/admin/customers/:id`, `/admin/customers/:id/contacts`;
      `ByRole` helper dispatches to the BM read-only page when
      `me.role === "BUILDING_MANAGER"`; `/admin/customers/new` +
      every other customer sub-route stays admin-only).
    - `frontend/src/layout/AppShell.tsx` (+~30 — customer-scoped
      submenu trimmed for BM: only Overview + Contacts; Buildings,
      Users, Permissions, Pricing, Extra Work, Settings hidden when
      `me.role === "BUILDING_MANAGER"`).
    - `frontend/src/i18n/en/common.json` and `nl/common.json` (each
      +26 keys covering page titles, read-only hints, section
      labels, empty states; EN/NL parity verified).
  - **New backend modules / tests:**
    - `backend/customers/tests/test_sprint28_bm_readonly.py` (22
      tests across 4 classes — `BMCustomerListDetailScopeTests` 7
      tests; `BMContactListDetailScopeTests` 7 tests;
      `BMContactAdminUnchangedTests` 6 tests; `BMWithoutAssignedBuildingTests`
      2 tests).
  - **New frontend modules:**
    - `frontend/src/components/CustomerReadRoute.tsx` — wrapper
      admitting SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER;
      bounces other roles to `/?admin_required=ok`.
    - `frontend/src/pages/admin/BuildingManagerCustomersPage.tsx` —
      read-only customer list (no Add button, no Edit links;
      `data-testid="bm-customers-page"`).
    - `frontend/src/pages/admin/BuildingManagerCustomerDetailPage.tsx`
      — read-only customer overview + Linked buildings + link to
      Contacts (no form controls; `data-testid="bm-customer-detail-page"`).
    - `frontend/src/pages/admin/BuildingManagerCustomerContactsPage.tsx`
      — read-only contact list + click-to-expand detail panel (no
      Add/Edit/Delete buttons; `data-testid="bm-customer-contacts-page"`).
  - **New Playwright spec:**
    - `frontend/tests/e2e/sprint28_bm_readonly_customers.spec.ts`
      — 4 cases: BM sees the read-only list (no Add button); BM
      detail is read-only (zero input/textarea/select controls);
      BM contacts page is read-only (no `.btn-primary` /
      `.btn-danger` / form controls); BM cannot reach
      `/admin/companies`, `/admin/buildings`, `/admin/users`,
      `/admin/services`, or `/admin/customers/new` — each redirects
      to `/?admin_required=ok` per `AdminRoute`.
- **Migration status:** NO migration created for Batch 12 — pure
  permission-class swap + new page components; no schema change.
  `makemigrations --dry-run --check`: No changes detected.
- **Tests / checks run:**
  - Targeted: `python manage.py test
    customers.tests.test_sprint28_bm_readonly` → **22/22 OK** in
    30.2s. Combined with the updated Batch 4 lock test → **31/31 OK**.
  - Backend customers+buildings+accounts sweep: **400/400 OK** in
    529.0s (initial run flagged the renamed Batch 4 lock test
    `test_building_manager_blocked_on_every_endpoint`; updated test
    now passes — the rename is intentional per the new Batch 12
    contract).
  - Broader sweep (`accounts tickets audit customers buildings`):
    **673/673 OK** in 746.1s — no regression.
  - `manage.py check`: 0 issues.
  - `makemigrations --dry-run --check`: No changes detected.
  - Frontend gates (re-verified via `wsl.exe -d Ubuntu bash -lic`):
    `tsc --noEmit -p tsconfig.app.json` → clean (EXIT=0);
    `vite build` → clean in 497ms; `eslint .` → **52 problems =
    baseline** (zero new hits — 3 `react-hooks/set-state-in-effect`
    suppressions via `// eslint-disable-line` on the data-loader
    `setLoading(true)` calls + `queueMicrotask` deferral for the
    `numericId === null` branches, both mirroring the existing
    Batch 4 `CustomerContactsPage` precedent).
  - Playwright spec **written but NOT executed locally** (WSL
    `frontend/test-results/` root-ownership gotcha; CI exercises).
- **Important decisions made (also in §9):**
  - **No new `osius.*` permission keys.** Reused
    `scope_customers_for(user)` (BM branch already implemented in
    Sprint 14) as the single source of truth for BM customer
    visibility. The new permission class is a thin wrapper around
    the existing scope helper + DRF `SAFE_METHODS`.
  - **`CustomerViewSet` UNCHANGED.** It already used
    `IsAuthenticatedAndActive` + `scope_customers_for` on read
    actions → BM already had read access. Writes are gated by
    `IsSuperAdminOrCompanyAdminForCompany` → BM already gets 403.
    Locked by the new `BMCustomerListDetailScopeTests`.
  - **Contacts gate widened on Batch 4 deferral.** The Batch 4
    completion log explicitly deferred BM read-only contact view
    to Batch 12. Batch 12 swaps the permission class on
    `CustomerContactListCreateView` + `CustomerContactDetailView`
    to admit BM on safe methods only.
  - **Frontend uses dedicated BM read-only pages, NOT a "read-only
    mode" flag on the admin pages.** `CustomerFormPage.tsx` is 1784
    lines and edit-bound; adding "read-only mode" inline would be
    invasive and decomposition is parked for Batch 13. Three new
    BM-only pages (each <200 lines) keep the diff small and
    purely additive.
  - **Sidebar trim**: BM customer-scoped submenu shows only
    Overview + Contacts; Buildings, Users, Permissions, Pricing,
    Extra Work, Settings hidden. Honours "no global admin access"
    and matches the route guards (those entries route to
    `AdminRoute`-protected pages which would bounce BM).
  - **`/admin/customers/new` stays admin-only.** BM has no create
    surface anywhere.
  - **Lint baseline preserved (52)** via the existing Batch 4
    `queueMicrotask` pattern for the `numericId === null` branch
    + `// eslint-disable-line` suffix on the `setLoading(true)`
    data-loader call (mirrors `CustomerPricingPage` /
    `CustomerContactsPage`).
- **Remaining risks:**
  - **`CustomerFormPage` decomposition still parked for Batch 13.**
    BM uses dedicated read-only pages rather than a "read-only
    mode" on the admin page. When Batch 13 decomposes the admin
    page, the BM variants can be retired in favour of unified
    view-first variants if the decomposition produces a clean
    read-mode/write-mode split.
  - **BM not yet exposed to the existing CustomerCompanyPolicy /
    visibility-flag surfaces.** Sprint 23B's
    `show_assigned_staff_*` flags on `Customer` are admin-write
    surfaces; BM has no surface for them and was always 403 on the
    Customer PATCH path. Batch 12 does not change this. The BM
    read-only customer detail page does NOT render the visibility
    flags — they're administrative-policy data not relevant to a
    BM read.
  - **Inline contact detail panel (in-page expand)** is the
    smallest-safe display surface. A more polished modal can land
    in a future polish batch if needed; the existing
    `CustomerContactsPage` admin modal is edit-bound and not
    appropriate for the read-only BM experience.

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

- [x] ~~Proposal PDF export via `fpdf2` (already in
      [`backend/requirements.txt`](../../backend/requirements.txt)).
      `GET /api/extra-work/proposals/<id>/pdf/` returns a styled PDF
      with every customer-visible field. `internal_note` never appears
      in the rendered bytes (string-search assertion in the test).~~
- [x] ~~Future subscription architecture doc —
      `docs/architecture/future-subscription-architecture.md`.
      Schema-shape only; no code. Per spec §9.1.~~
- [x] ~~Future bank matching architecture doc —
      `docs/architecture/future-bank-matching-architecture.md`. Schema
      slot description (`external_reference`, `paid_at`, `paid_amount`);
      no code. Per spec §9.2.~~

---

## 7. Current batch pointer

- **Current batch:** **SPRINT 28 COMPLETE.** All 14 batches closed.
- **Current status:** Done. Batch 14 (Proposal PDF + future-architecture
  docs) shipped 2026-05-19.
- **Next recommended action:** Open a post-Sprint-28 follow-on sprint to
  pick up the remaining view-first decomposition work
  (`UserFormPage` 1091 lines, `BuildingFormPage` 544 lines,
  `CompanyFormPage` 502 lines — listed under master plan §6 Batch 13
  but explicitly out of scope per the user's focused-cleanup brief).
  Subscription / bank-matching feature sprints land later when
  scheduled, against the contracts in
  [`docs/architecture/future-subscription-architecture.md`](../architecture/future-subscription-architecture.md)
  and
  [`docs/architecture/future-bank-matching-architecture.md`](../architecture/future-bank-matching-architecture.md).
- **Next recommended batch (on-deck):** Post-Sprint 28 cleanup sprint
  for the remaining view-first decompositions.

### Batch 13 — completion log

- **Date:** 2026-05-18
- **Commit:** uncommitted on working tree as of 2026-05-18, on top of `8185d94`
- **Rework history (2026-05-18):** A first attempt landed only structural
  route-splitting (new pages with the same visual rhythm as the old
  form), plus a small dashboard toggle wrapping the two-pasted-dashboard
  Batch 9 layout. User rejected it as "messy, scattered, empty,
  admin-CRUD-like". The rework substantially rewrites
  `CustomerOverviewPage.tsx`, `CustomerUsersPage.tsx`,
  `CustomerSettingsPage.tsx`, `DashboardPage.tsx`, and the `index.css`
  helper-class family. Everything below describes the *post-rework*
  state.
- **Files changed summary:**
  - **Frontend pages (created / under `frontend/src/pages/admin/customer/`):**
    - `CustomerSubPageHeader.tsx` (63 lines, shared back-link + name +
      active/inactive badge header + optional action slot).
    - `CustomerOverviewPage.tsx` (445 lines, REAL view-first overview):
      `.section-explainer` paragraph naming the actual provider company
      and the linked-buildings count; 4-card clickable `.summary-grid`
      stat strip with live counts via `listCustomerBuildings` /
      `listCustomerUsers` / `listCustomerContacts` / `listCustomerPrices`
      (each card links to its sub-page); linked-buildings preview card
      (first 5 + "View all (N)" footer; empty-state copy when 0); 6-tile
      `.quicklink-grid` of Management areas with icon + title + one-
      sentence description (Contacts / Buildings / Users / Permissions /
      Pricing / Extra work). NO permission radios, NO policy toggles,
      NO override buttons — Playwright lock preserved.
    - `CustomerPermissionsPage.tsx` (1000 lines): per-access role/active/
      override editor + CustomerCompanyPolicy panel; preserves every
      Sprint 27E testid (`customer-access-role-select`,
      `customer-access-overrides-button`, `customer-overrides-row`,
      `customer-overrides-radio`, `customer-overrides-save`,
      `customer-overrides-close`, `customer-policy-toggle`,
      `customer-policy-save`); now also opens with a `.section-explainer`
      paragraph naming the customer and pointing to the Users tab.
    - `CustomerBuildingsPage.tsx` (355 lines): `.section-explainer` at
      top with the customer/building service-relationship rule; stat
      pill showing `{N} buildings linked`; existing add/unlink table now
      has `customer-buildings-table` testid + typed empty-state
      `customer-buildings-empty`.
    - `CustomerUsersPage.tsx` (383 lines): `.section-explainer` at top
      pointing operators to the Permissions tab; new per-user **access
      summary** column showing `.customer-user-access-pill` rows
      ("Building name · Location manager"; dimmed when inactive) sourced
      via the existing `listCustomerUserAccess` aggregate; clear
      `customer-user-row` / `customer-user-access-summary` testids;
      empty-state for zero members.
    - `CustomerSettingsPage.tsx` (344 lines): `.section-explainer` at
      top; Card 1 "Assigned-staff visibility" with the three flag
      toggles + a single helper paragraph explaining each; Card 2
      "Lifecycle" with deactivate/reactivate button + consequence copy
      ("Deactivating disables logins…"; "Reactivating restores logins…").
      Preserves `contact-visibility-section`, `show-assigned-staff-*`,
      `deactivate-button`, `reactivate-button` testids.
  - **`frontend/src/pages/DashboardPage.tsx` REWRITTEN as one
    `.operations-dashboard` composition** (1522 lines vs 1226 before):
    - **Top KPI strip** — single `.operations-kpi-grid` 5-card row
      (Total open work / Active tickets / Active extra work / Awaiting
      approval / Urgent) computed client-side from
      `TicketStats` + `ExtraWorkStats` (NEVER aggregated from a single
      page of /tickets/ results). All five cards equal-weight via
      `min-height: 110px`; grid collapses 5 → 3 → 2 columns at 1280px /
      720px. testids `dashboard-ops-kpi-row` + per-card
      `dashboard-ops-kpi-{total|tickets|extra-work|awaiting|urgent}`.
      `kpi-urgent` modifier on the Urgent card.
    - **Work strip** — `.work-strip` card-like band directly under the
      KPI row containing a small "Show:" label + three pill buttons
      ("All work" / "Tickets only" / "Extra work only") with `aria-pressed`
      styling. URL-backed `?view=all|tickets|extra-work`. testids
      `dashboard-work-view-{toggle|all|tickets|extra-work}`.
    - **Work area** — `.work-layout` 1fr + 340px (collapses to 1fr at
      1100px):
      - `view=all`: main column is ONE unified "Recent operational
        items" card (`dashboard-recent-ops`) — a single table whose
        rows are tickets with a leading `.work-type-pill` (Ticket /
        Extra work) and columns Type / Subject / Customer / Building /
        Status / Updated, showing the first 8 tickets; below the table
        inside the same card a slim "extra-work shortcut" row honestly
        reflects the API limitation ("{N} extra-work requests open ·
        View all extra work"). Side column = two stacked compact cards
        "Tickets by building" + "Extra work by building" (the EW one
        keeps `dashboard-extra-work-section` for backward-compat
        assertions). NO duplicate "Status breakdown" cards. NO per-half
        KPI rows.
      - `view=tickets`: existing Sprint 12 tickets surface (filters bar
        + ticket table + pagination on left, "Tickets by building" +
        status breakdown on right) inside the new shell. Per-section KPI
        row gone (top strip already covers it).
      - `view=extra-work`: existing extra-work data inside the new shell
        (main: by-building expanded; side: status breakdown). NO per-
        section KPI row. Empty-state `dashboard-extra-work-section-empty`
        renders here when `extraWorkStats.total === 0`.
    - Removed: floating `.work-view-toggle`, `.dashboard-two-col`
      wrapper, the two per-section KPI rows, and the duplicate "Status
      breakdown" rendering.
  - **`frontend/src/index.css` (+294 lines):** new operations-dashboard
    family — `.operations-dashboard`, `.operations-kpi-grid`,
    `.work-strip`, `.work-strip-label`, `.work-strip-toggle`,
    `.work-layout`, `.work-type-pill` (+ `-ticket` / `-extra-work`
    variants), `.recent-ops-extra-work-row`; new customer-overview
    family — `.section-explainer`, `.summary-grid`, `.summary-stat`,
    `.summary-stat-label`, `.summary-stat-value`, `.summary-stat-meta`,
    `.quicklink-grid`, `.quicklink-card`, `.quicklink-card-head`,
    `.quicklink-card-desc`, `.customer-user-access-pills`,
    `.customer-user-access-pill` (+ `.inactive` modifier). Old
    `.work-view-toggle*` rules removed (no longer referenced).
  - **`frontend/src/App.tsx` routes:** `/admin/customers/:id` admin
    variant → `CustomerOverviewPage`; new `/admin/customers/:id/edit`
    → `CustomerFormPage` (preserved); `/buildings`, `/users`,
    `/permissions`, `/settings` → dedicated pages; `/admin/customers/new`,
    `/extra-work`, `/pricing`, `/contacts` unchanged. BM Batch 12
    `ByRole` dispatcher routes BM to `BuildingManagerCustomerDetailPage`
    / `BuildingManagerCustomerContactsPage` exactly as before.
  - **i18n EN/NL parity verified:** `en/common.json` 721 keys ==
    `nl/common.json` 721 keys (set diff empty); `en/dashboard.json` 95
    keys == `nl/dashboard.json` 95 keys. Adds `customer_view.overview.*`
    (incl. `explainer_with_provider` / `explainer_generic` /
    `stat_linked_buildings` / `stat_customer_users` / `stat_contacts` /
    `stat_pricing` / `buildings_preview_*` / six `quicklink_*_desc`),
    `customer_view.buildings.{explainer,count_summary}`,
    `customer_view.users.{explainer,no_access_yet}`,
    `customer_view.permissions.explainer`,
    `customer_view.settings.{explainer,visibility_helper,lifecycle_title,deactivate_consequence,reactivate_consequence}`,
    and dashboard `ops_kpi_*_label/_meta` × 5 + `ops_recent_*` +
    `ops_type_*` + `ops_byb_*`. All Dutch translations sentence-case.
  - **`CustomerFormPage.tsx`, `CustomerSubPagePlaceholder.tsx`,
    `AppShell.tsx` UNTOUCHED.** Form preserved as basics editor + create
    flow. Placeholder still serves `/admin/customers/:id/extra-work`
    until that sub-route gets a real page in a future sprint.
  - **Frontend tests:**
    - `frontend/tests/e2e/sprint28_batch13_view_first.spec.ts` (new) —
      extended to 6 cases (overview-no-perm + 5 new asserts on stat
      strip, buildings preview, quicklinks; permissions has policy
      toggle; BM still readonly; buildings page not a placeholder;
      users page shows access summary; dashboard top KPI row + recent
      ops card + work toggle).
    - `frontend/tests/e2e/sprint28_extra_work_dashboard.spec.ts`
      (updated for Batch 13 contract): test 2 swaps the deprecated
      `dashboard-extra-work-kpi-awaiting-customer` testid for the
      unified `dashboard-ops-kpi-awaiting`; test 3 clicks the
      `dashboard-work-view-extra-work` toggle before asserting the
      empty-state (the dedicated extra-work view is where the empty-
      state now lives). Test 1 unchanged (both section testids still
      resolve in `view=all`).
  - Backend: ZERO source changes. No new tests. No migration. No
    permission keys.
  - Docs: this completion block + §7 pointer advance + §8 log row.
- **Tests / checks run (post-rework):**
  - Frontend `tsc --noEmit -p tsconfig.app.json`: clean (EXIT=0).
  - Frontend `vite build`: clean, 388ms (`index-Ca9AYrUU.js` 902.12 kB
    gzip 222.76 kB; CSS 65.93 kB gzip 11.71 kB); advisory chunk-size
    warning is pre-existing baseline (not from this diff).
  - Frontend `eslint .`: **52 problems = baseline** (49 errors + 3
    warnings). Zero new lint hits in changed files — new pages defer
    null-check branches into `queueMicrotask` (mirrors
    `BuildingManagerCustomerDetailPage.tsx` + `CustomerContactsPage.tsx`
    precedent) and suppress only the synchronous `setLoading(true)`
    inside `useEffect`.
  - Backend `manage.py check`: 0 issues (unchanged — ZERO backend code
    touched).
  - Backend `makemigrations --dry-run --check`: No changes detected.
  - Backend broader sweep (`accounts tickets audit customers buildings
    --keepdb -v 1`): **673/673 OK** in 527.7s (task `bj5k4gxlg` from
    pre-rework run; result still authoritative since no backend code
    changed in the rework).
  - Playwright specs written but NOT executed locally (WSL
    `frontend/test-results/` root-ownership gotcha; CI exercises 6
    Batch 13 cases + 3 updated Batch 9 cases).
- **Important decisions made (post-rework):**
  - **Dashboard is ONE composition, not two stacked.** The pre-rework
    Sprint 28 Batch 9 layout had two parallel sections (each with its
    own KPI row, its own dash-grid, and its own Status breakdown card),
    and the first Batch 13 attempt simply wrapped them in a toggle.
    User rejected that as "two pasted dashboards". The rework subsumes
    both into a single `.operations-dashboard` composition: one 5-KPI
    top strip + one work-strip band + one work-layout that switches
    content by `view`. The duplicate "Status breakdown" cards are gone.
  - **Unified Recent operational items table.** `view=all` renders one
    table whose rows carry a `.work-type-pill` (Ticket / Extra work).
    The backend does not expose a mixed-feed endpoint today, so the
    table is the first 8 tickets followed by a slim "extra-work
    shortcut" row inside the same card honestly reflecting the API
    limitation — no fake "EW preview table" sourced from stats.
  - **CustomerFormPage preserved, not replaced.** The 1784-line form
    stays as the basics editor at `/admin/customers/:id/edit` and as
    the create flow at `/admin/customers/new`. Decomposing the editor
    itself was deemed beyond Batch 13's focused-cleanup scope (user
    asked for clarity, not a giant redesign); the form still works,
    just no longer doubles as the Overview/Permissions surface.
  - **Permissions split is route-level, not component-level.** Both
    sub-routes (`/admin/customers/:id` and `/admin/customers/:id/permissions`)
    formerly rendered the same `CustomerFormPage`; they now render
    `CustomerOverviewPage` and `CustomerPermissionsPage` respectively.
    This is the structural fix for the user's "Overview and Permissions
    look duplicate" complaint.
  - **CustomerOverviewPage carries real content, not just tiles.**
    Provider-company-naming explainer + 4-card live-count stat strip +
    linked-buildings preview + 6-tile management areas grid. The page
    answers "what is this customer and what can I do with it?" on first
    paint, without scrolling.
  - **Per-user access summary lives on Users tab, not Permissions.**
    The Users page lists each member with their per-building access
    pills (sourced via the existing `listCustomerUserAccess` aggregate);
    detailed permission editing remains on the Permissions tab. The
    user's complaint "Users page is empty" is addressed without
    duplicating the Sprint 27E editor.
  - **Settings is a real settings page.** Two cards (Assigned-staff
    visibility + Lifecycle) with consequence copy. No more lump of
    checkboxes wedged into the basics form.
  - **Updated existing `sprint28_extra_work_dashboard.spec.ts`** to
    align with the new unified dashboard contract — within Batch 13
    scope because the dashboard rewrite removed two deprecated testids
    (`dashboard-extra-work-kpi-awaiting-customer`,
    `dashboard-extra-work-section-empty` in `view=all`). The semantic
    contract is preserved (CUSTOMER_USER still sees the awaiting bucket;
    STAFF still sees an empty-state for extra work) — just on different
    testids.
  - **Dashboard work-view URL state.** `?view=all|tickets|extra-work`
    in the location search params; missing/invalid values fall back to
    `all`. Choice was URL-backed so a shared dashboard link preserves
    the selection across refreshes (consistent with the existing
    `?sla=` filter pattern in DashboardPage).
  - **Data fetches early-return on hidden sections.** When `view !==
    "tickets"`, the ticket-list and stats loaders bail before the API
    call — the section is hidden anyway and fetching would waste bandwidth
    + paint nothing. Same pattern for extra-work loaders. Auto-refresh
    cadence unchanged.
  - **No global customer-context provider.** Each new sub-page does its
    own `getCustomer(id)` fetch in a `useEffect`. A shared provider
    would have meaningfully changed the architecture; Batch 13 prefers
    a tiny amount of duplication to keep the diff focused.
  - **Reactivate-button surfaces on Overview AND Settings.** Both pages
    have legitimate reasons to expose the reactivate CTA (Overview is
    the deep-link landing target; Settings is where lifecycle controls
    live). Both are gated to SUPER_ADMIN + customer.is_active === false.
  - **`CustomerSubPagePlaceholder.tsx` retained for `/extra-work` only.**
    The route is parked until the per-customer Extra Work surface ships
    in a future sprint; removing the placeholder file would break that
    route.
- **Remaining risks:**
  - **`CustomerFormPage` is still 1784 lines.** Its basics editor at
    `/admin/customers/:id/edit` retains the original
    company/building/name/email/phone/language form PLUS the legacy
    buildings + users + permissions + policy sections lower down the
    page (the file was preserved unchanged to avoid risk). Admins
    landing on `/edit` therefore still see the old mega-page; the
    Overview / Permissions / Buildings / Users / Settings sub-routes
    are the canonical surfaces. Future Batch can either (a) decompose
    `CustomerFormPage` into a minimal basics-only form, or (b) redirect
    `/edit` to the matching sub-page based on what the operator wants
    to change.
  - **`UserFormPage` (1091 lines), `BuildingFormPage` (544 lines),
    `CompanyFormPage` (502 lines) untouched.** Master plan §6 Batch 13
    listed these too; the user's focused-cleanup brief deliberately
    narrowed scope to the customer detail page + dashboard. Track as
    post-Sprint 28 follow-on.
  - **No new lint disable comments in changed files** — verified by
    diff inspection. `queueMicrotask` pattern handles the
    `react-hooks/set-state-in-effect` rule on the empty-state branches.
  - **`/admin/customers/:id/edit` is a NEW URL.** Direct deep-links to
    older bookmarks like `/admin/customers/:id` still work (they now
    land on Overview, not the edit form). The "Edit basics" CTA on
    Overview is the documented path to reach the form.
  - **Playwright spec uses "B Amsterdam"** as the demo seed customer
    name — same convention as `sprint28_contacts.spec.ts`,
    `sprint23c_access_role_editor.spec.ts`, and
    `sprint28b_customer_sidebar.spec.ts`. The customer id is resolved
    at runtime via `/api/customers/?page_size=200` so reseeds don't
    break the spec.

---

## 8. Completion log

Append-only. Newest at the top. One row per closed batch.

| Date | Batch | Commit | Summary | Tests/checks | Remaining risks |
|---|---|---|---|---|---|
| 2026-05-19 | Batch 14 — Proposal PDF + future-architecture docs | uncommitted on working tree as of 2026-05-19, on top of `ae8cde7` | **Backend-only PDF export + two future-architecture markdown docs.** New module `backend/extra_work/proposal_pdf.py` (332 lines) — pure function `render_proposal_pdf(proposal, *, viewer_is_customer)` using `fpdf2` (already in requirements). Safeguards baked in: `pdf.set_compression(False)` so test byte-search assertions resolve; `_safe_pdf_text` helper substitutes `€` → `EUR`, em/en-dashes → `-`, curly quotes → straight, plus final `latin-1 errors='replace'` defensive pass to avoid the classic fpdf2 `Character not in font` crash; currency always rendered as `EUR x.xx` plain text. PDF composition: title row + provider/customer/building header + parent EW context (description + urgency) + per-line table (service/description, qty × unit_type, unit_price, vat%, line subtotal/vat/total) with per-line `customer_explanation` indented below each row + totals footer + provider-only override block (`override_reason` + override actor email — entirely OMITTED for customer viewers). **`internal_note` is NEVER read in the renderer** — verified by grep (`internal_note` appears only in comment/docstring warnings against introducing it). New view `ProposalPdfView` in `backend/extra_work/views_proposals.py` (read-only — inherits scope + DRAFT-invisibility via `_resolve_proposal_or_404`; does NOT emit `CUSTOMER_VIEWED` timeline event unlike `ProposalDetailView`; does NOT save, does NOT call `emit_proposal_event`, does NOT call `recompute_totals` — verified by grep). New URL `<int:ew_id>/proposals/<int:pid>/pdf/` named `extra-work-proposal-pdf`. Response: `HttpResponse(pdf_bytes, content_type="application/pdf")` + `Content-Disposition: inline; filename="proposal-<pid>.pdf"`. **NEW backend tests** `backend/extra_work/tests/test_sprint28_proposal_pdf.py` (421 lines, 11 cases): PDF 200 for SA + customer on SENT + 404 for customer on DRAFT + 403/404 for STAFF + 404 cross-tenant customer + `internal_note` byte-search NEVER appears for SA + same for customer + override_reason in provider PDF + override_reason omitted in customer PDF + read-only-no-timeline-event lock + unicode-safe rendering. **NEW docs:** [`docs/architecture/future-subscription-architecture.md`](../architecture/future-subscription-architecture.md) — `SubscriptionPlan` + `SubscriptionExecution` schema shape with cadence enum, scheduler outline via Celery Beat, customer-side UX placeholder, open questions parked (billing trigger ownership, ad-hoc interaction, approval cadence, provider override). [`docs/architecture/future-bank-matching-architecture.md`](../architecture/future-bank-matching-architecture.md) — `BankTransaction` schema with `external_reference` / `paid_at` / `paid_amount` slot description on the eventual receivable owner (Proposal vs. Ticket vs. Subscription decision deferred), matching engine outline, provider-only API surface, open questions parked (receivable owner, refunds/partials, bank feed source, reconciliation reporting, tax export). Both docs explicitly state "no columns added today" per master plan §2A.9 anti-premature-columns rule. **ZERO migration. ZERO new permission keys. ZERO frontend code touched.** | Backend `manage.py check`: 0 issues. `makemigrations --dry-run --check`: No changes detected. Backend targeted (`extra_work.tests.test_sprint28_proposal_pdf`): **11/11 OK** in 1.2s. Backend `extra_work` sweep (per backend agent): **193/193 OK** in 86.1s — no regressions. Broader backend sweep (`accounts tickets audit customers buildings extra_work --keepdb -v 1`) running as task `bz6kcfetd` at finalisation; expected ~866 tests OK by analogy with Batch 12 baseline (673) + Batch 8 extra_work cohort (193). | **`fpdf2` Latin-1 font limitation** — the `_safe_pdf_text` helper handles common European punctuation + non-Latin-1 fallback, but extremely exotic glyphs (CJK, Arabic, emoji) would degrade to `?`. Acceptable for cleaning-services receipts. **PDF rendering is uncompressed** (`set_compression(False)`) so test byte-search assertions resolve reliably. Production PDFs will be slightly larger than they could be — trade-off accepted for testability. **No customer-side frontend surface yet** — the new endpoint is wired but no React page mounts the "Download PDF" button on the customer-facing proposal view; that's a future polish item parked outside Batch 14 scope (master plan §6 Batch 14 has zero frontend bullets). Operators / customers can hit the endpoint directly. **`CUSTOMER_VIEWED` timeline event is NOT emitted on PDF reads** — contrary to `ProposalDetailView` which does emit it. The PDF endpoint is a read-only rendering of an already-visible resource; the test `test_pdf_emits_no_timeline_event` pins this contract. Future polish may decide to mirror the JSON-detail event emission; if so, that's a deliberate spec change with audit-trail consequence. **Two future-architecture docs are normative going forward** — when subscription / bank-matching sprints land, their kick-off briefs must cite these contracts, not invent new schemas. |
| 2026-05-18 | Batch 13 — View-first refactor + dashboard rework (reworked after UX rejection) | uncommitted on working tree as of 2026-05-18, on top of `8185d94` | **Frontend-only batch. Reworked once after the first attempt's dashboard layout was rejected as "two pasted dashboards" and customer sub-pages as "empty placeholder-like".** The rework substantially rewrites the dashboard composition and `CustomerOverviewPage` / `CustomerUsersPage` / `CustomerSettingsPage`, while keeping the new route structure from the first attempt. **New pages under `frontend/src/pages/admin/customer/`:** `CustomerSubPageHeader.tsx` (shared back-link + name + active/inactive badge + optional action slot), `CustomerOverviewPage.tsx` (read-only summary card with `<dl className="readonly-grid">` for linked-buildings-count / contact email / phone / language / active; 6-tile QuickLinks grid pointing at Contacts/Buildings/Users/Permissions/Pricing/Extra work; "Edit basics" CTA links to `/admin/customers/:id/edit`; reactivate-button surfaced for SUPER_ADMIN when customer is inactive; testids `customer-overview-page`, `customer-overview-quicklinks`, `customer-overview-edit-basics`, `customer-overview-linked-buildings-count`, `customer-overview-explainer`, `customer-overview-quicklink-*`; NO permission radios / policy toggles / override buttons — load-bearing contract for the Playwright spec), `CustomerPermissionsPage.tsx` (per-access role select + active toggle + override editor section + CustomerCompanyPolicy form; preserves all Sprint 27E testids `customer-access-role-select`, `customer-access-overrides-button`, `customer-overrides-row`, `customer-overrides-radio`, `customer-overrides-save`, `customer-overrides-close`, `customer-policy-toggle`, `customer-policy-save`; new `customer-permissions-page` testid), `CustomerBuildingsPage.tsx` (linked-buildings table + add/unlink with `ConfirmDialog`), `CustomerUsersPage.tsx` (members add/remove WITHOUT permission pills + hint link "Edit permissions in the Permissions tab"; testid `customer-users-permissions-hint`), `CustomerSettingsPage.tsx` (contact-visibility toggles `show_assigned_staff_name/email/phone` + deactivate/reactivate dialogs; preserves `contact-visibility-section`, `show-assigned-staff-*`, `deactivate-button`, `reactivate-button`). **`App.tsx` route changes:** `/admin/customers/:id` admin variant now mounts `CustomerOverviewPage` (BM still `ByRole`-routed to `BuildingManagerCustomerDetailPage` — Batch 12 preserved exactly); `/admin/customers/:id/edit` is a NEW admin-only route that re-mounts the preserved `CustomerFormPage` so the basics editor is still reachable; `/buildings`, `/users`, `/permissions`, `/settings` swapped from `CustomerSubPagePlaceholder` / `CustomerFormPage` to the new dedicated pages; `/admin/customers/new`, `/extra-work`, `/pricing`, `/contacts` UNCHANGED. **`DashboardPage.tsx`:** three-segment work-view toggle (All work / Tickets only / Extra work only) above the existing Tickets + Extra Work sections; URL-backed under `?view=all|tickets|extra-work`; conditional render on both `<section>` blocks; early-return guards in the four data loaders (`loadTickets`, `loadStats`, `loadStatsByBuilding`, two extra-work loaders) so hidden sections skip their fetches; testids `dashboard-work-view-toggle`, `-all`, `-tickets`, `-extra-work`. **`index.css`:** added `.work-view-toggle`, `.work-view-toggle-label`, `.work-view-toggle-button-active` rules. **i18n EN/NL parity:** +25 `customer_view.*` keys in `common.json` (includes i18next plurals `linked_buildings_count_one` / `_other`); +4 `work_view_*` keys in `dashboard.json`. **`CustomerFormPage.tsx`, `CustomerSubPagePlaceholder.tsx`, `AppShell.tsx` UNTOUCHED** — form preserved as basics editor + create flow; placeholder still serves `/extra-work`; sidebar already had separate Overview + Permissions entries (they now just point at different pages). New Playwright spec `sprint28_batch13_view_first.spec.ts` (4 cases — overview-no-perm; permissions-renders-policy-toggle; BM-still-readonly; dashboard work-view toggle). ZERO backend code touched; no new `osius.*` / `customer.*` keys; no migrations; no new permission classes. BM Batch 12 read-only routing preserved exactly. | Frontend `tsc --noEmit -p tsconfig.app.json`: EXIT=0 clean. `vite build`: clean in 353ms; only pre-existing chunk-size advisory. `eslint .`: **52 problems = baseline** (49 errors, 3 warnings) — confirmed zero new lint hits in changed files (`CustomerPermissionsPage.tsx` deferred its empty-state `setAccessByUserId({})` into `queueMicrotask` mirroring the Batch 4 `CustomerContactsPage` precedent). Backend `manage.py check`: 0 issues. `makemigrations --dry-run --check`: No changes detected. Broader backend sweep (`accounts tickets audit customers buildings --keepdb -v 1`): **673/673 OK** in 527.7s (task `bj5k4gxlg`) — exact parity with Batch 12's identical scope; zero regressions as expected for a frontend-only batch. Playwright spec written but NOT executed locally (WSL `frontend/test-results/` root-ownership gotcha; CI exercises the 4 cases). | **`CustomerFormPage` is still 1784 lines** — preserved as basics editor + create flow; the file still bundles legacy buildings/users/permissions/policy sections lower down the page, so admins who land on `/edit` see the old mega-page. The decomposition target was the `/admin/customers/:id` Overview surface, which is now clean. Future batch can either (a) decompose `CustomerFormPage` into a basics-only minimal form, or (b) redirect `/edit` to the matching sub-page based on what the operator wants to change. **`UserFormPage` (1091 lines), `BuildingFormPage` (544 lines), `CompanyFormPage` (502 lines) untouched** — listed under master plan §6 Batch 13 but explicitly out of scope per the user's focused-cleanup brief; track as post-Sprint 28 follow-on. **`/admin/customers/:id/edit` is a NEW URL** — old bookmarks to `/admin/customers/:id` still resolve (they now show Overview); the "Edit basics" CTA on Overview is the documented path. **Playwright spec uses "B Amsterdam"** demo seed customer (consistent with `sprint28_contacts.spec.ts`, `sprint23c_access_role_editor.spec.ts`, `sprint28b_customer_sidebar.spec.ts`); customer id resolved at runtime via `/api/customers/?page_size=200`. **QuickLinks tiles have no hover styling** — uses the existing `.card` class; visual polish deferred. **`CustomerSubPagePlaceholder.tsx` retained** for `/extra-work` only; removing it would break that route until the per-customer Extra Work surface ships in a future sprint. |
| 2026-05-18 | Batch 12 — BM read-only customer/contact view | uncommitted on working tree as of 2026-05-18, on top of `48bead6` | Joint backend + frontend, read-only customer/contact surfaces for BUILDING_MANAGER in their assigned-building scope. **Backend:** new `IsSuperAdminOrCompanyAdminOrBuildingManagerReadCustomer` permission class in `accounts/permissions.py` (admits BM on safe methods only when the customer is in `scope_customers_for(user)`; defers to the existing `IsSuperAdminOrCompanyAdminForCompany` semantics for unsafe methods / admin roles); applied to `views_contacts.py` for both `CustomerContactListCreateView` + `CustomerContactDetailView`. `CustomerViewSet` UNCHANGED — already correctly behaved for BM via `IsAuthenticatedAndActive` + `scope_customers_for` on reads + `IsSuperAdminOrCompanyAdminForCompany` on writes. NO new `osius.*` permission keys. NO migration (pure permission-class swap + new page components). Batch 4 regression-lock test `test_building_manager_blocked_on_every_endpoint` renamed to `test_building_manager_blocked_on_write_endpoints` and body updated to reflect the new Batch 12 contract (BM=200 on GET in scope, BM=403 on POST/PATCH/DELETE). 22 new backend tests across 4 classes in `test_sprint28_bm_readonly.py` covering: BM customer list/retrieve in scope; BM cross-scope 404; BM customer write 403 (create/update/delete/reactivate); BM contact list/retrieve in scope; BM out-of-scope customer-contact 403; BM contact write 403 (create/update/delete); SUPER_ADMIN + COMPANY_ADMIN contact behaviour unchanged; STAFF + CUSTOMER_USER on contacts still 403; bare BM (no `BuildingManagerAssignment`) sees zero customers and 403 on contacts. **Frontend:** new `CustomerReadRoute.tsx` wrapper admitting SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER; bounces other roles to `/?admin_required=ok` matching `AdminRoute` pattern. `App.tsx` swaps three route guards from `AdminRoute` to `CustomerReadRoute` (`/admin/customers`, `/admin/customers/:id`, `/admin/customers/:id/contacts`); new `ByRole` helper dispatches to BM-variant component when `me.role === "BUILDING_MANAGER"`. `/admin/customers/new` + all other customer sub-routes (`/buildings`, `/users`, `/permissions`, `/extra-work`, `/pricing`, `/settings`) stay admin-only. Three new BM-only pages: `BuildingManagerCustomersPage.tsx` (read-only customer list; no Add button; testid `bm-customers-page`), `BuildingManagerCustomerDetailPage.tsx` (read-only customer overview + linked buildings + link to Contacts; zero form controls; testid `bm-customer-detail-page`), `BuildingManagerCustomerContactsPage.tsx` (read-only contact list + click-to-expand detail panel; no Add/Edit/Delete buttons; testid `bm-customer-contacts-page`). `AppShell.tsx` customer-scoped submenu trimmed for BM — only Overview + Contacts visible; Buildings / Users / Permissions / Pricing / Extra Work / Settings hidden when `me.role === "BUILDING_MANAGER"`. EN/NL i18n parity: +26 keys per locale (page titles "Customers in your assigned buildings" / "Klanten in je toegewezen gebouwen"; read-only hints; section labels; empty states). New Playwright spec `sprint28_bm_readonly_customers.spec.ts` (4 cases — BM read-only list no Add button; BM detail no form controls; BM contacts no `.btn-primary`/`.btn-danger`/form controls; BM blocked from `/admin/companies`, `/admin/buildings`, `/admin/users`, `/admin/services`, `/admin/customers/new`). | Backend targeted (`test_sprint28_bm_readonly`): **22/22 OK** in 30.2s. Combined with updated Batch 4 lock (`test_sprint28_contacts.ContactScopeIsolationTests`): **31/31 OK**. Customers + buildings + accounts sweep: **400/400 OK** in 529.0s (initial run flagged the renamed Batch 4 test; updated body now passes per the new Batch 12 contract). Broader sweep (`accounts tickets audit customers buildings`): **673/673 OK** in 746.1s — no regression. `manage.py check`: 0 issues. `makemigrations --dry-run --check`: No changes detected. Frontend `tsc --noEmit -p tsconfig.app.json` → clean (EXIT=0); `vite build` → clean in 497ms; `eslint .` → **52 problems = baseline** (zero new hits; the data-loader `setLoading(true)` is suppressed with `// eslint-disable-line` mirroring `CustomerPricingPage`/`CustomerContactsPage` precedent, and the `numericId === null` branches use `queueMicrotask` deferral mirroring the existing Batch 4 `CustomerContactsPage` pattern). Playwright spec written but NOT executed locally (WSL gotcha; CI exercises). | **`CustomerFormPage` decomposition still parked for Batch 13** — BM uses dedicated read-only pages rather than a read-only-mode toggle on the admin page; CustomerFormPage is 1784 lines and inline read-only mode would be invasive. Future Batch 13 can retire the BM variants if decomposition produces a clean read-mode/write-mode split. **BM has no surface for `Customer.show_assigned_staff_*` visibility flags** (admin-write fields; BM always 403 on Customer PATCH); BM read-only detail intentionally does NOT render these. **Inline contact detail panel** (in-page expand) is the smallest-safe display surface; the existing admin modal pattern is edit-bound and not appropriate for read-only BM experience. **No global admin access for BM** — Playwright spec asserts `/admin/companies`, `/admin/buildings`, `/admin/users`, `/admin/services`, `/admin/customers/new` all bounce BM to the dashboard with `?admin_required=ok`. **Renamed Batch 4 lock test**: `test_building_manager_blocked_on_every_endpoint` → `test_building_manager_blocked_on_write_endpoints` — semantic rename reflects the new Batch 12 contract (BM is NOT blocked on reads anymore); test body updated, not new test added (preserves the baseline test count). |
| 2026-05-17 | Batch 11 — Staff completion routing | uncommitted on working tree as of 2026-05-17, on top of `3d91810` | Joint backend + frontend, configurable per-staff/per-building STAFF completion routing per product rule #7. **Backend:** new `TicketStatus.WAITING_MANAGER_REVIEW` enum value + new `Ticket.manager_review_at: DateTimeField(null=True, blank=True)` column (migration `tickets/0010_waiting_manager_review.py`, `AlterField` regenerates choices + `AddField` for the timestamp). New `BuildingStaffVisibility.staff_completion_routes_to_customer: BooleanField(default=False)` flag (migration `buildings/0004_bsv_staff_completion_routes_to_customer.py`; per-staff-per-building granularity per rule #7; default False preserves manager-review default route). 4 new `ALLOWED_TRANSITIONS` entries: `(IN_PROGRESS, WAITING_MANAGER_REVIEW)` (STAFF default route + SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER on-behalf), `(IN_PROGRESS, WAITING_CUSTOMER_APPROVAL)` EXTENDED with STAFF row (gated by routing-flag at runtime), `(WAITING_MANAGER_REVIEW, WAITING_CUSTOMER_APPROVAL)` (BM accepts), `(WAITING_MANAGER_REVIEW, IN_PROGRESS)` (BM rejects). New `SCOPE_STAFF_ASSIGNED` scope helper (TicketStaffAssignment membership). `TIMESTAMP_ON_ENTER` extended to stamp `manager_review_at`. `COMPLETION_EVIDENCE_TRANSITIONS` extended to include `(IN_PROGRESS, WAITING_MANAGER_REVIEW)` — same Sprint 25C rule (note OR visible attachment required). New STAFF routing-flag check + BM-rejection-note check in `apply_transition` with stable codes `staff_completion_route_mismatch` + `rejection_note_required` (both also enforced at serializer for view-layer 400 + defence in depth). `TicketDetailSerializer` extended with `is_assigned_staff: bool` SerializerMethodField + `manager_review_at` field (frontend uses `is_assigned_staff` to gate the "Complete work" button without a separate API call). New `@action` on `TicketViewSet` at `GET /api/tickets/<id>/staff-completion-route/` returning `{"route": "manager_review" | "customer_approval"}` for the frontend modal to render the correct destination text + submit-button label. `BuildingStaffVisibilitySerializer` + `BuildingStaffVisibilityUpdateSerializer` extended with the new flag as a writable field (necessary surface extension mirroring Batch 10's `visibility_level` rollout). Audit: `_BSV_TRACKED_FIELDS` extended to include `"staff_completion_routes_to_customer"`; existing UPDATE-diff handler covers the new field. NO new `osius.*` permission keys (model-field + scope-check pattern from Batch 10). `views_staff_assignments.py::_gate_actor` UNCHANGED — multi-staff M:N endpoint remains admin-only (PM Q5; same Batch 10 decision). H-5 invariant preserved: STAFF still has no row in `(WAITING_CUSTOMER_APPROVAL → APPROVED/REJECTED)` — the new STAFF transitions are "STAFF marking own work done", structurally distinct from "approving customer completion". 34 new backend tests across 11 classes (`test_sprint28_staff_completion.py` 31 tests + `test_sprint28_staff_completion_route_audit.py` 3 tests): structural transitions, default route, configured route, completion evidence × 4 sub-cases × 2 routes, route mismatch, STAFF-not-assigned forbidden, H-5 STAFF-cannot-approve lock, BM accepts, BM rejects with + without note, endpoint authorization matrix, audit row shape. **Frontend:** new types `WAITING_MANAGER_REVIEW` in `TicketStatus` union + `manager_review_at` + `is_assigned_staff` on `TicketDetail` + `StaffCompletionRoute` + `StaffCompletionRouteResponse` + `BuildingStaffVisibilityAdmin.staff_completion_routes_to_customer` + extended `StaffVisibilityPatch`. New API helper `getStaffCompletionRoute(ticketId)`. `TicketDetailPage.tsx` gets STAFF "Complete work" button (gated on `STAFF + IN_PROGRESS + is_assigned_staff`) + inline-card completion modal mirroring the Sprint 27F-F1 override modal shape (required note textarea + attachment hint + routing-aware destination text from the new endpoint + routing-aware submit label; handlers for `completion_evidence_required` inline error + `staff_completion_route_mismatch` refetch). Testids: `ticket-staff-complete-button`, `-modal`, `-route`, `-note`, `-error`, `-cancel`, `-submit`. `UserFormPage.tsx` `StaffDetailsSection` BSV editor gets new "Completion routes directly to customer" checkbox stacked under `can_request_assignment` (desktop + mobile mirror; testids `staff-completion-routes-to-customer-{buildingId}` + `-mobile-{buildingId}`). 17 new i18n keys per locale, EN/NL parity verified. New Playwright spec `staff-completion-routing.spec.ts` (2 cases — STAFF modal flow + admin checkbox toggle persistence; status verified via API not locale badge text for resilience). Docs: H-5 matrix row clarified (STAFF-marks-own-work-done vs customer-decision) + new §15 Test footprint section; audit row 18 marked OK with Batch 11 reference. | Backend targeted (`test_sprint28_staff_completion + test_sprint28_staff_completion_route_audit`): **34/34 OK** in 8.0s. Backend broader (`accounts tickets audit customers buildings`): **644/644 OK** in 719.7s (parent session re-verification — matches backend agent's 644/644 result). `manage.py check`: 0 issues. `makemigrations --dry-run --check`: No changes detected. Frontend gates from agent environment: `tsc --noEmit -p tsconfig.app.json` → clean (no errors); `vite build` → clean in 619ms (2789 modules); `eslint .` → **52 problems = baseline** (zero new hits — the 7 hits inside `TicketDetailPage.tsx` + `UserFormPage.tsx` are pre-existing `react-hooks/set-state-in-effect` warnings on untouched useEffect blocks). Parent session cannot independently re-verify (WSL/UNC cmd.exe gotcha — `'tsc' is not recognized`); CI will confirm on push. Playwright spec written but NOT executed locally (WSL `frontend/test-results/` root-ownership gotcha; CI exercises). | **Dev DB schema BEHIND code** — THREE pending migrations: Batch 10's `buildings/0003_buildingstaffvisibility_visibility_level` (still not applied from prior commit) + Batch 11's `buildings/0004_bsv_staff_completion_routes_to_customer` + `tickets/0010_waiting_manager_review`. User must run `python manage.py migrate buildings tickets` to catch up. Endpoints touching `WAITING_MANAGER_REVIEW`, `manager_review_at`, `visibility_level`, or `staff_completion_routes_to_customer` will raise `column does not exist` errors against the dev container until applied. **Inline attachment upload inside completion modal is UX debt** — deferred per PM Q12 + backend-engineer report; modal directs operator to existing Attachments card on the page. Backend's `completion_evidence_required` rule still accepts note-only completions. **Frontend gates not independently re-runnable from parent session** — same WSL/UNC cmd.exe limitation as prior batches; agent environments verified green. **EW staff completion routing UNIMPLEMENTED** — parked because STAFF has no EW scope today (G-B7). Future batch can add `staff_completion_routes_to_customer_extra_work` parallel column without collision. **`change_status` view UNCHANGED** — STAFF passes `is_staff_role(...)` (Sprint 23A widened) → reaches serializer + state machine where new logic applies. View-layer touch was unnecessary. **Provider on-behalf completion** supported in `ALLOWED_TRANSITIONS` (SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER listed) but frontend exposes no dedicated UI surface; admins use generic status-change. Acceptable for Batch 11 scope. **Playwright spec resolves status via API** (not locale badge text) for resilience against future i18n copy changes. |
| 2026-05-17 | Batch 10 — Staff per-building granularity | uncommitted on working tree as of 2026-05-17, on top of `eb689a1` | Joint backend + frontend, per-row STAFF visibility level on `BuildingStaffVisibility`. **Backend:** new `BuildingStaffVisibility.VisibilityLevel` TextChoices enum (`ASSIGNED_ONLY` / `BUILDING_READ` / `BUILDING_READ_AND_ASSIGN`); new `visibility_level` CharField with `default=BUILDING_READ` (preserves existing B2 behaviour for every existing BSV row + Sprint 24-28 staff test). Migration `buildings/0003_buildingstaffvisibility_visibility_level.py` (single AddField; backfills automatically). `accounts/scoping.py` STAFF branch updated: only `BUILDING_READ` / `BUILDING_READ_AND_ASSIGN` rows contribute building-wide visibility; `ASSIGNED_ONLY` rows recognise STAFF at the building (for direct-assignment-target eligibility via `_validate_target_staff`) but do NOT widen visibility beyond `TicketStaffAssignment`. H-4 floor (`Q(_assigned=True)`) preserved untouched. `tickets/views.py::assign` action widened: STAFF allowed iff active BSV row exists for `ticket.building_id` with `visibility_level=BUILDING_READ_AND_ASSIGN`. `TicketAssignSerializer.validate` (`tickets/serializers.py`) mirror-widened — necessary deviation: the existing Sprint 28 Batch 2 serializer gate was rejecting all STAFF before view-layer code could fire; both layers now share the same B3 BSV-level check (defence in depth). `views_staff_assignments.py::_gate_actor` UNCHANGED — the multi-staff M:N `TicketStaffAssignment` stays admin-only (PM Q5: B3 maps to BM-assign verb, not multi-staff orchestration). NO new `osius.*` keys (PM Q6: model field is the source of truth). `BuildingStaffVisibilitySerializer` extended with `visibility_level` as a writable field. Audit signal: `_BSV_TRACKED_FIELDS` extended from `("can_request_assignment",)` to include `"visibility_level"`. 19 new backend tests across 9 classes (`test_sprint28_staff_building_granularity.py`) covering default, B1/B2/B3 scope + assign-gate, cross-building + cross-company isolation, target-validation unchanged, H-4 floor (finally dedicated coverage — closes audit row 25 doc-drift), multi-staff endpoint still admin-only; +1 audit test for `visibility_level` UPDATE diff. **Frontend:** new `StaffVisibilityLevel` string-literal union + `visibility_level` field on `BuildingStaffVisibilityAdmin` in `api/types.ts`; `updateStaffVisibility` helper refactored to take a `StaffVisibilityPatch` object (avoids field clobber when toggling one of the two writable fields). `UserFormPage.tsx` `StaffDetailsSection` gets new per-row dropdown in desktop table column + mobile card (`data-testid="staff-visibility-level-select-{buildingId}"`) — smallest-safe addition, no redesign. `DashboardPage.tsx` gets conditional "Assigned to you" badge on STAFF rows where `ticket.assigned_to === me.id` (desktop subject cell + phone-width ticket card); sort-first parked as remaining UX debt. 5 new i18n keys per locale (`staff_admin.level_*` + `tickets.assigned_to_you`), EN/NL parity. New Playwright spec `staff-building-granularity.spec.ts` (2 cases — dropdown renders + three options exist). Matrix doc updated: §1.2 BSV row mentions visibility_level; §3 H-4 paragraph references the new `StaffH4FloorTests`; new §14 Test footprint section. Audit doc updated: row 17 status → OK with Batch 10 reference; row 26 noted as PARTIAL (view + serializer halves closed; deeper serializer audit follow-up still open). | Backend targeted (`test_sprint28_staff_building_granularity + test_sprint28_visibility_level_audit`): **19/19 OK** in 5.1s. Backend broader (`accounts tickets audit customers`): **585/585 OK** in 471.9s — no regression to existing Sprint 24-28 STAFF tests. Backend full suite (per backend agent's environment): **1032/1032 OK**. `manage.py check`: 0 issues. `makemigrations --dry-run --check`: No changes detected. Frontend typecheck (agent env): EXIT=0 clean. Frontend lint (agent env): **52 problems = baseline** (zero new hits in changed files). Frontend `vite build`: failed environmentally (rolldown `win32-x64-msvc` native binding missing in WSL — same class of WSL/UNC limitation as prior batches; CI builds cleanly). Playwright spec written, NOT executed locally (WSL `frontend/test-results/` root-ownership gotcha). | **Dev DB schema BEHIND code** until user approves `python manage.py migrate buildings` — `accounts/scoping.py` will raise `column does not exist` against the dev container until applied. **`vite build` not re-runnable from parent session** (rolldown native binding through WSL UNC bridge). **Sort-first prioritisation for own-assigned tickets parked** as remaining UX debt — badge ships; sort would require role-gated shared-list reordering. **`TicketAssignSerializer.validate` deep audit (audit row 26) remains open** — Batch 10 widened the gate consistently across view + serializer; a formal boolean-edge-case audit of the serializer is a follow-up. **Badge does NOT honour multi-staff M:N** — fires only on `ticket.assigned_to === me.id` (legacy single-assignee FK); M:N check requires per-row staff-assignments fetch, deferred. |
| 2026-05-17 | Batch 9 — Extra Work dashboard and stats | uncommitted on working tree as of 2026-05-17, on top of `ec66380` | Joint backend + frontend, aggregation-only batch (no new models, no new migrations). **Backend:** two new `@action` methods on `ExtraWorkRequestViewSet` at `backend/extra_work/views.py` — `GET /api/extra-work/stats/` returns `{total, by_status, by_routing, by_urgency, active, awaiting_pricing, awaiting_customer_approval, urgent}`; `GET /api/extra-work/stats/by-building/` returns a list of per-building rows `{building_id, building_name, total, active, awaiting_pricing, awaiting_customer_approval, urgent}` ordered by `building_name`, GROUP BY naturally skips zero-row buildings. Both reuse `scope_extra_work_for(request.user)` so H-1/H-2 isolation is inherited; STAFF naturally gets all-zeros because the scope helper returns `.none()` for STAFF (MVP). Two module-level constants `EXTRA_WORK_TERMINAL_STATUSES = ("CUSTOMER_APPROVED", "CUSTOMER_REJECTED", "CANCELLED")` and `EXTRA_WORK_AWAITING_PRICING_STATUSES = ("REQUESTED", "UNDER_REVIEW")` shared between both actions. `awaiting_customer_approval` defined as `status == PRICING_PROPOSED` only (Option A from PM Q2; Batch 8's `apply_proposal_transition` auto-advance contract makes parent EW status the single source of truth — OR-ing in `proposals__status=SENT` would double-count). `awaiting_pricing` = `routing_decision="PROPOSAL"` AND `status IN (REQUESTED, UNDER_REVIEW)` — the operator action queue. `urgent` = `urgency="URGENT"` AND `status NOT IN terminal`. No new permission keys; no migration. **Frontend:** new typed helpers `getExtraWorkStats()` + `getExtraWorkStatsByBuilding()` in `frontend/src/api/extraWork.ts` (Option A from PM Q2); new TS types `ExtraWorkStatusValue` / `ExtraWorkRoutingValue` / `ExtraWorkUrgencyValue` (string-literal unions) + `ExtraWorkStats` / `ExtraWorkStatsByBuildingRow` / `ExtraWorkStatsByBuildingResponse` in `frontend/src/api/types.ts` next to existing `TicketStats` types. `DashboardPage.tsx` ADDITIVE Extra Work section parallel to existing Tickets layout — both top-level `<section>`s wrapped in `<div className="dashboard-two-col">` that renders them **side by side at viewports ≥ 1400px** (CSS Grid `minmax(0, 1fr) minmax(0, 1fr)` with `align-items: start`) and stacked at narrower widths. `<section data-testid="dashboard-tickets-section">` wraps existing Tickets layout untouched, new `<section data-testid="dashboard-extra-work-section">` next to it with 5-KPI row (Total / Active / Awaiting pricing / Awaiting customer / Urgent) + by-building card + status-breakdown card (visual symmetry with Tickets). Empty-state container `data-testid="dashboard-extra-work-section-empty"` when `total === 0 && Object.keys(by_status).length === 0` (STAFF / no-scope users). CUSTOMER_USER gets emphasis class on `data-testid="dashboard-extra-work-kpi-awaiting-customer"`. `frontend/src/index.css` carries the new `.dashboard-two-col` rule + 1400px media query (breakpoint chosen higher than the inner `.dash-grid` 1100px breakpoint so the Tickets section's `1fr + 340px` split stays functional inside the half-viewport column); `minmax(0, 1fr)` is load-bearing to prevent the inner recent-tickets table from overflowing the column. New Extra Work loaders merged into existing tickets-stats `useEffect` to avoid a new `react-hooks/set-state-in-effect` lint hit. Same `AUTO_REFRESH_INTERVAL_MS` cadence. EN/NL i18n parity: +26 keys per locale in `dashboard.json` covering section title/sub, 5 KPI label/meta pairs, by-building title/sub + empty + 4 `{{count}}` count templates, empty section copy, 6 Extra Work status labels under `extra_work_status_*`. New backend test module `backend/extra_work/tests/test_sprint28_extra_work_stats.py` (19 tests / 5 classes — scope across SUPER_ADMIN/COMPANY_ADMIN/BUILDING_MANAGER/CUSTOMER_USER/STAFF, 8 bucket-definition tests, by-building order + zero-row skip + per-row aggregate match, H-1/H-2 cross-tenant isolation lock, soft-delete excluded). New Playwright spec `frontend/tests/e2e/sprint28_extra_work_dashboard.spec.ts` (3 tests — provider sees both sections; CUSTOMER_USER sees awaiting-customer emphasis; STAFF sees empty state). | Backend targeted: `python manage.py test extra_work.tests.test_sprint28_extra_work_stats --keepdb -v 1` → **19/19 OK** in 4.9s. Backend broader: `python manage.py test extra_work tickets audit customers --keepdb -v 1` → **535/535 OK** in 363.1s — no regression. `manage.py check`: 0 issues. `makemigrations --dry-run --check`: No changes detected. Frontend in agent environment: `tsc --noEmit -p tsconfig.app.json` → **EXIT=0 clean (strict mode)**; `eslint .` → **52 problems = baseline** (zero new hits in changed files). Frontend gates NOT independently re-run from parent session (WSL/UNC cmd.exe gotcha — well-documented operational limitation). `vite build` NOT run (env mismatch in agent sandbox, unrelated to Batch 9 code; CI exercises on Linux). Playwright spec written but NOT executed locally (WSL `frontend/test-results/` gotcha; CI will exercise the 3 cases). | **At viewports < 1400px the sections stack vertically** — by design (responsive default). Users on 1366×768 / 1440×900 laptop screens may see stacked sections; 1440px+ external monitors see side-by-side. The 1400px breakpoint can be lowered to 1280px or 1200px in a future polish batch if stakeholders want a wider side-by-side range, but lowering further would cramp the Tickets inner `1fr + 340px` split. **Frontend gates not independently re-run from the parent session** — typecheck + lint passed in the frontend agent's environment; CI will confirm on push. **`vite build` not run locally** (Node 20.18 < required 20.19 in agent sandbox + rolldown UNC binding mismatch — unrelated to Batch 9 code; CI builds cleanly). **Auto-refresh loader merged into existing tickets-stats effect** to avoid a new `react-hooks/set-state-in-effect` lint hit (existing effect already trips this rule baseline; new loaders added to it rather than a fresh effect). **`ExtraWorkRequest` still NOT registered for audit** — proposal-driven auto-advance writes do not land on generic AuditLog (pre-existing Batch 6 deferral; surfacing again because Batch 9 surfaces these state changes in the dashboard counts). Stats reads do NOT depend on AuditLog so this risk is information-only. **Status-breakdown card** rendered for visual symmetry with the Tickets section (PM brief made it optional; frontend agent kept it). **Playwright spec needs CI run to confirm behaviour against demo seed** — light assertions only, no count assertions (seed-data-dependent). |
| 2026-05-17 | Batch 8 — Proposal builder | `ec66380 feat: add extra work proposal builder` (on top of `7ec3f15`) | **Backend-only batch** (master plan §6 Batch 8 has zero frontend bullets — PM scope-verification confirmed). Ships the first-class proposal entity for the custom-priced (`routing_decision="PROPOSAL"`) Extra Work path. **4 new models in `extra_work/models.py`**: `Proposal` (FK ExtraWorkRequest CASCADE; status enum DRAFT/SENT/CUSTOMER_APPROVED/CUSTOMER_REJECTED/CANCELLED; stored totals + `recompute_totals` mirroring `ExtraWorkRequest`; sent_at/customer_decided_at/override_by/override_reason/override_at; partial `UniqueConstraint(extra_work_request, condition=Q(status__in=["DRAFT","SENT"]))` named `uniq_proposal_open_per_request` permits 1:N parent→proposals but blocks parallel open drafts), `ProposalLine` (FK Proposal CASCADE + nullable FK Service PROTECT; ad-hoc `description` CharField required when service is NULL; quantity/unit_type/unit_price/vat_pct; **`customer_explanation` + `internal_note` TextField pair per spec §6 / PM Q1 default**; `is_approved_for_spawn: bool=True` forward-compat slot for parked per-line UX; stored computed `line_subtotal`/`line_vat`/`line_total` recomputed in `save()` mirroring `ExtraWorkPricingLineItem`), `ProposalStatusHistory` (mirrors `ExtraWorkStatusHistory` shape — `is_override`+`override_reason` columns ARE the workflow-override audit trail per H-11), `ProposalTimelineEvent` (event_type enum {CREATED/SENT/CUSTOMER_VIEWED/CUSTOMER_APPROVED/CUSTOMER_REJECTED/ADMIN_OVERRIDDEN/CANCELLED}; `customer_visible: bool` written at emission time; provider-only `metadata: JSONField` carries override_reason text for ADMIN_OVERRIDDEN events; customer serializer strips metadata entirely). **New state machine `backend/extra_work/proposal_state_machine.py`**: 5-entry `ALLOWED_TRANSITIONS` set (DRAFT→SENT, DRAFT→CANCELLED, SENT→CUSTOMER_APPROVED, SENT→CUSTOMER_REJECTED, SENT→CANCELLED); `_user_can_drive_proposal_transition` mirrors `extra_work.state_machine` (SUPER_ADMIN global; COMPANY_ADMIN/BUILDING_MANAGER scoped via reused `osius.ticket.view_building`; CUSTOMER_USER via `customer.extra_work.approve_own`/`approve_location`; STAFF blocked); `apply_proposal_transition` is atomic + select_for_update + emits one timeline event per transition + writes one history row. **Override coercion mirrors Sprint 27F-B1**: provider-driven SENT→CUSTOMER_APPROVED/REJECTED + provider-driven SENT→CANCELLED coerce `is_override=True` and require `override_reason` (HTTP 400 with stable code `override_reason_required`). **Parent-EW auto-advance BYPASSES `extra_work.state_machine.apply_transition`** to avoid the legacy `pricing_line_items_required` precondition: SENT writes UNDER_REVIEW→PRICING_PROPOSED on parent + an `ExtraWorkStatusHistory` row directly in the same atomic block; CUSTOMER_APPROVED writes PRICING_PROPOSED→CUSTOMER_APPROVED; CUSTOMER_REJECTED writes PRICING_PROPOSED→CUSTOMER_REJECTED; override fields propagate to parent EW too. `Proposal.send` REJECTS if parent is in REQUESTED (operator must drive REQUESTED→UNDER_REVIEW manually first) — HTTP 400 stable code `proposal_send_requires_under_review`. **New spawn service `backend/extra_work/proposal_tickets.py::spawn_tickets_for_proposal(proposal, *, actor)`** parallel to Batch 7's `instant_tickets.py`: atomic (caller-held tx), idempotent (skip lines whose `Ticket.proposal_line` already resolves), respects `is_approved_for_spawn=False` (forward-compat), uses customer_explanation NOT internal_note in ticket description, sets `Ticket.proposal_line` FK, writes initial `TicketStatusHistory` OPEN row, returns list of created Tickets. **New `Ticket.proposal_line`** nullable FK (`SET_NULL` on delete; `related_name="spawned_tickets_for_proposal_line"`) parallel to Batch 7's `extra_work_request_item` FK — Option A from PM Q5a (carries divergent unit_price/quantity/customer_explanation that would be lost if Option B reused the cart-line FK). **Migration `extra_work/0004_proposal_models.py`** (4 tables + UniqueConstraint + 3 indexes) + **migration `tickets/0009_ticket_proposal_line.py`** (cross-app FK, depends on `extra_work.0004_proposal_models`). **7 new API endpoints** under `/api/extra-work/<ew_id>/proposals/` (list/create, detail, transition, status-history, timeline, lines list/create, line detail) — provider-only mutations gated by `osius.ticket.view_building` scope helper; customer GET filters DRAFT out of list + 404s on DRAFT detail; customer GET of SENT detail emits CUSTOMER_VIEWED timeline event. **Audit:** Proposal + ProposalLine added to full-CRUD tuple in `audit/signals.py`; **ProposalStatusHistory + ProposalTimelineEvent intentionally NOT registered (H-11)** — the history rows ARE the workflow-override audit trail; regression-locked by `ProposalTimelineEventNotAuditedTests`. **47 new backend tests across 3 modules**: `test_sprint28_proposal.py` (30 tests / 13 classes covering CRUD, parent-EW advancement, customer visibility, dual-note privacy with JSON grep-assert, approve+spawn, reject, provider override, atomicity rollback via monkeypatched Ticket.create, idempotency including is_approved_for_spawn=False, timeline emission, scope across all roles, STAFF exclusion, re-send after rejection, unique-open-proposal constraint), `test_sprint28_proposal_state_machine.py` (10 tests / 3 classes for structural state machine), `test_sprint28_proposal_audit.py` (7 tests / 3 classes including the H-11 lock). | Backend targeted (3 modules, 47 tests): **47/47 OK** in 15.7s. Backend broader (`extra_work tickets audit customers`): **516/516 OK** in 352.4s — no regression. Backend full suite (per backend-engineer report): **994/994 OK**. `manage.py check`: 0 issues. `makemigrations --dry-run --check`: No changes detected. No frontend files touched (intentionally — backend-only batch); no frontend checks run. | **Dev DB schema applied 2026-05-17** by user via `python manage.py migrate extra_work tickets` — proposal endpoints exercisable against the dev container. **No frontend exposure** of the proposal builder yet — Batch 8 has zero frontend bullets per master plan §6. Operators cannot compose a proposal via UI until Batch 9 (EW dashboard) or a dedicated frontend batch ships the builder UX. **`Proposal` CREATE writes TWO AuditLog rows** by design (CREATE row + immediate UPDATE for `recompute_totals` save). Audit test asserts on the CREATE row specifically; consumers should be aware. **`CUSTOMER_VIEWED` emitted on every customer GET** of a SENT proposal — not deduplicated. Future polish item. **Parent EW `CUSTOMER_REJECTED → UNDER_REVIEW` must be driven manually** by operator before a new proposal can be POSTed against the same parent. **`Ticket.proposal_line` is `SET_NULL` on ProposalLine delete** — spawn-origin history lost if a line is deleted post-spawn (same trade-off as Batch 7's `extra_work_request_item`). **`ExtraWorkRequest` still NOT registered for audit** — parent EW writes from proposal-driven auto-advance do not land on generic AuditLog (pre-existing Batch 6 deferral; future sprint must pick up these propagation diffs deliberately when registering the parent). |
| 2026-05-16 | Batch 7 — Instant-ticket path | `afdbf91 feat: spawn tickets for instant extra work` (on top of `4fe16d5`) | **Backend-only batch** (master plan §6 Batch 7 has zero frontend bullets). Atomic spawn of one `tickets.Ticket` per `ExtraWorkRequestItem` for cart submissions where Batch 6 computed `routing_decision="INSTANT"`. New nullable FK `Ticket.extra_work_request_item` (SET_NULL on delete, `related_name="spawned_tickets"`) carries the traceability link. Migration `tickets/0008_ticket_extra_work_request_item.py` (cross-app dependency on `extra_work.0003_request_items_and_routing`). New state-machine transition `REQUESTED → CUSTOMER_APPROVED` reuses the existing status; gated as **system-only** via new `SYSTEM_ONLY_TRANSITIONS` set rejected for every actor in `_user_can_drive_transition` BEFORE role checks — customers cannot bypass the resolver via `POST /api/extra-work/<id>/transition/`. Spawn service `backend/extra_work/instant_tickets.py::spawn_tickets_for_request(request, *, actor)` called from `ExtraWorkRequestCreateSerializer.create()` inside the existing `transaction.atomic()`. Per-line `resolve_price()` is **re-called at spawn time** as a defensive abort: if any line returns None (despite Batch 6 routing_decision=INSTANT) the spawn raises `TransitionError(code="instant_spawn_price_lost")` and the whole submission rolls back. Idempotent: skips items whose `Ticket.extra_work_request_item` already resolves. Each spawned Ticket: company/building/customer from request, created_by=actor, title=`f"{service.name} × {quantity}"`, description = request.description + line customer_note + service.description, priority=NORMAL, status=OPEN, plus an initial `TicketStatusHistory` row. The parent request transitions REQUESTED→CUSTOMER_APPROVED with `ExtraWorkStatusHistory` row (note "instant-route: all lines contract-priced"). `Ticket` intentionally NOT audit-registered (per H-11; lifecycle goes via `TicketStatusHistory`). `ExtraWorkRequest` intentionally NOT audit-registered (Batch 6 lock unchanged). 15 new backend tests across 6 classes (`test_sprint28_instant_tickets.py`); 3 Batch 6 tests rewritten to reflect the new contract (was "no spawn yet" → now "INSTANT spawns + status advances; PROPOSAL still no-op"). | Backend targeted (`test_sprint28_instant_tickets + test_sprint28_cart_request`): **36 tests OK** in 6.6s. Backend broader sweep (`extra_work tickets audit customers`): **469/469 OK** in 336.0s — no regression. `manage.py check`: 0 issues. `makemigrations --dry-run --check`: No changes detected. No frontend files touched (intentionally — backend-only batch); no frontend checks run. | **Dev DB schema applied** 2026-05-16 by user via `python manage.py migrate tickets` — `showmigrations tickets` shows `[X] 0008_ticket_extra_work_request_item`; instant-ticket spawn path now exercisable against the dev container. `TransitionError → 500` propagation in the create view: defensive `instant_spawn_price_lost` raises `TransitionError` which the create view doesn't catch (mirrors existing pattern — only the `transition` view has a try/except). Surfaced status is 500 not 400; race window is microseconds; unreachable under normal operation. **No frontend exposure of spawned-ticket IDs yet** — Batch 6 result panel still shows just `INSTANT`/`PROPOSAL` banner. Master plan §6 Batch 7 has zero frontend bullets so deliberately deferred (likely lands in Batch 9 EW dashboard). **State-machine system-only gate is load-bearing** — if a future refactor removes the `SYSTEM_ONLY_TRANSITIONS` check, customers could bypass the resolver via `POST /transition/`. `SystemOnlyTransitionTests` (4 cases) locks this. **Backlog `EXTRA-INSTANT-TICKET-1` row** mentions transitioning to `IN_PROGRESS (or new INSTANTIATED)` — stale wording; code uses `CUSTOMER_APPROVED` per PM recommendation. Update the backlog row in the closeout commit. |
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
| 2026-05-18 | **NO new `osius.*` permission keys for Batch 12.** Reused `scope_customers_for(user)` (existing Sprint 14 BM branch already encodes "BM sees customers linked to any of their assigned buildings via M:N `CustomerBuildingMembership` OR legacy `Customer.building`") + DRF `SAFE_METHODS`. The new permission class `IsSuperAdminOrCompanyAdminOrBuildingManagerReadCustomer` is a thin wrapper. | Same pattern as Batches 10 + 11 — model-field/scope-helper as the source of truth; "do not invent parallel keys when an existing one expresses the same scope" (master plan §2 "do not rename osius.*" extends in spirit). Adding `osius.customer.view_assigned_building` etc. would have required a parallel resolver branch + new admin UI surface for zero functional gain. Locked by `BMCustomerListDetailScopeTests` + `BMContactListDetailScopeTests` + `BMWithoutAssignedBuildingTests`. | Batch 12 + `backend/accounts/permissions.py::IsSuperAdminOrCompanyAdminOrBuildingManagerReadCustomer` + `backend/accounts/scoping.py::customer_ids_for` BM branch |
| 2026-05-18 | **`CustomerViewSet` UNCHANGED**. It already correctly returned BM-scoped customers via `IsAuthenticatedAndActive` + `scope_customers_for` on read actions and gated writes via `IsSuperAdminOrCompanyAdminForCompany` (which excludes BM). The Batch 12 changes are confined to (a) the contacts views' permission gate and (b) the frontend BM-variant pages. | The audit at `docs/audits/current-state-2026-05-16-system-audit.md` row 12 had already noted "customers admin list/detail works for BM" pre-batch — the only actual gap was contacts (deferred from Batch 4 to Batch 12). Touching `CustomerViewSet` would have been scope creep. Locked by `BMCustomerListDetailScopeTests` (7 tests pin both read-OK-in-scope and write-403-by-role). | Batch 12 + `backend/customers/views.py` (untouched) + PM Q1 |
| 2026-05-18 | **Three dedicated BM read-only pages, NOT a "read-only mode" flag on `CustomerFormPage` / `CustomerContactsPage`.** Each BM page is <200 lines and purely additive. The admin pages are untouched. | `CustomerFormPage.tsx` is 1784 lines and edit-bound (Sprint 27E permission editor, customer policy panel, etc.); inline read-only mode would be invasive and decomposition is Batch 13 territory. `CustomerContactsPage.tsx` (731 lines) has a similar edit-modal pattern. Dedicated BM pages keep the diff small, purely additive, and let Batch 13 retire them cleanly if decomposition produces a clean read-mode/write-mode split. Locked by Playwright spec asserting `dashboard-tickets-section` is absent / `bm-customer-detail-page` is present + zero form controls in the BM detail page. | Batch 12 + `frontend/src/pages/admin/BuildingManagerCustomers*Page.tsx` + `frontend/tests/e2e/sprint28_bm_readonly_customers.spec.ts` |
| 2026-05-18 | **Renamed Batch 4 regression-lock test `test_building_manager_blocked_on_every_endpoint` → `test_building_manager_blocked_on_write_endpoints`** with body rewritten to reflect the new Batch 12 contract: BM=200 on GET in-scope; BM=403 on POST/PATCH/DELETE. The read-side BM behaviour is locked in the new `test_sprint28_bm_readonly.py` module. | The original test name explicitly asserted "blocked on every endpoint" — which is no longer true post-Batch-12. Renaming + reshaping (rather than deleting + re-creating) preserves the test count and keeps the audit trail. The new behaviour is identical to what `IsSuperAdminOrCompanyAdminOrBuildingManagerReadCustomer` enforces. | Batch 12 + `backend/customers/tests/test_sprint28_contacts.py::ContactScopeIsolationTests::test_building_manager_blocked_on_write_endpoints` |
| 2026-05-18 | **BM customer-scoped sidebar trimmed to Overview + Contacts** in `AppShell.tsx`. Buildings / Users / Permissions / Pricing / Extra Work / Settings hidden when `me.role === "BUILDING_MANAGER"`. | The hidden entries route to admin-only sub-routes that `AdminRoute` would bounce BM from. Hiding them prevents dead links + clarifies the BM persona's surface (read customer + contacts; nothing else). Honours product rule §3 ("no data dumps") + Batch 12's "no global provider settings access" requirement. Locked by Playwright spec assertions hitting `/admin/companies`, `/admin/buildings`, `/admin/users`, `/admin/services` and confirming the redirect to `/?admin_required=ok`. | Batch 12 + `frontend/src/layout/AppShell.tsx` customer-scoped submenu |
| 2026-05-17 | **`WAITING_MANAGER_REVIEW` added as a new `TicketStatus` enum value** (between `IN_PROGRESS` and `WAITING_CUSTOMER_APPROVAL` chronologically). Migration `tickets/0010_waiting_manager_review.py` regenerates `choices` via `AlterField` (column type unchanged; existing rows unaffected). New `Ticket.manager_review_at: DateTimeField(null=True, blank=True)` timestamp column added in the same migration; `TIMESTAMP_ON_ENTER` updated so `apply_transition` stamps it automatically. | Master plan §6 Batch 11 fourth bullet + §10 Open Question 2 default both explicitly name `WAITING_MANAGER_REVIEW` as the new status for the default route ("Staff marks done → `WAITING_MANAGER_REVIEW` → Building Manager accepts → `WAITING_CUSTOMER_APPROVAL` or rejects back to `IN_PROGRESS`"). The user's pre-batch brief said "Do NOT add WAITING_MANAGER_REVIEW unless the master plan explicitly requires it and you justify it first" — it explicitly does. Adding the timestamp column lets the timeline/analytics surface (existing pattern for `sent_for_approval_at`, `approved_at`, etc.) capture the manager-review entry point. Locked by `StaffCompletionTransitionStructuralTests` + `StaffDefaultRouteTests`. | Batch 11 + `backend/tickets/models.py::TicketStatus` + `backend/tickets/migrations/0010_waiting_manager_review.py` + PM Q1 |
| 2026-05-17 | **Routing flag = `BuildingStaffVisibility.staff_completion_routes_to_customer: BooleanField(default=False)`** (per-staff-per-building, on the BSV row — NOT on `StaffProfile`). Affirmative naming (`routes_to_customer` not `skip_manager_review`) keeps `True` as the active deviation from the conservative default. Migration `buildings/0004_bsv_staff_completion_routes_to_customer.py`. | Product rule #7 (master plan §5 lines 178-181) explicitly says "Optional (per staff/building, separately for Tickets vs Extra Work): Staff marks done → directly to customer approval" — per-building granularity is required. `StaffProfile` is per-staff-global and cannot express the per-building rule. The BSV row IS the per-staff-per-building anchor (it was extended with `visibility_level` in Batch 10 for the same reason). Default `False` preserves the manager-review default route for every pre-Batch-11 row + every existing test. Field name explicit on the Ticket side so a future EW equivalent can land as a parallel column (`staff_completion_routes_to_customer_extra_work`) without collision when STAFF gets EW scope. Audit coverage via `_BSV_TRACKED_FIELDS` tuple extension (existing UPDATE-diff handler covers). | Batch 11 + `backend/buildings/models.py::BuildingStaffVisibility.staff_completion_routes_to_customer` + PM Q2 |
| 2026-05-17 | **Four new `ALLOWED_TRANSITIONS` entries** (1 NEW transition + 1 EXTENDED + 2 NEW for WAITING_MANAGER_REVIEW outbound): `(IN_PROGRESS, WAITING_MANAGER_REVIEW)` (STAFF default route + SUPER_ADMIN/COMPANY_ADMIN/BUILDING_MANAGER on-behalf); `(IN_PROGRESS, WAITING_CUSTOMER_APPROVAL)` EXTENDED with STAFF row gated by the routing-flag check; `(WAITING_MANAGER_REVIEW, WAITING_CUSTOMER_APPROVAL)` (BM accepts); `(WAITING_MANAGER_REVIEW, IN_PROGRESS)` (BM rejects). New `SCOPE_STAFF_ASSIGNED` scope constant + branch in `_user_passes_scope` (`TicketStaffAssignment` membership check). | The state machine is the single source of truth for what STAFF can drive structurally. Per master plan §6 Batch 11. The flag-gating happens IN-LINE in `apply_transition` (PM Q5 Option A) not in the scope helper — keeps the scope helper pure (membership only) and puts the routing-flag check next to the existing Sprint 27F-B1 override-coercion + Sprint 25C completion-evidence preconditions. Provider operators (SUPER_ADMIN/COMPANY_ADMIN/BUILDING_MANAGER) can drive the on-behalf transitions without the flag-gate — the flag is STAFF-only policy. Locked by `StaffCompletionTransitionStructuralTests` + `StaffRouteMismatchTests` + `BMAcceptsStaffCompletionTests` + `BMRejectsStaffCompletionTests`. | Batch 11 + `backend/tickets/state_machine.py::ALLOWED_TRANSITIONS` + `_user_passes_scope` + PM Q3 + Q4 + Q5 |
| 2026-05-17 | **STAFF routing-flag check sits in `apply_transition`, not in the scope helper** (PM Q5 Option A). When STAFF drives `IN_PROGRESS → {WAITING_MANAGER_REVIEW, WAITING_CUSTOMER_APPROVAL}`, the helper looks up the BSV row's `staff_completion_routes_to_customer` value and compares to the actor's chosen `to_status`. Mismatch → `TransitionError(code="staff_completion_route_mismatch")` (HTTP 400). Provider operators bypass this gate — flag is a STAFF-only policy. | Encoding the flag in the scope helper would have leaked policy into scope semantics + required either two parallel scopes (`SCOPE_STAFF_ASSIGNED_DEFAULT_ROUTE` / `SCOPE_STAFF_ASSIGNED_CUSTOMER_ROUTE`) or a flag-state-aware helper. Keeping it in `apply_transition` keeps the architectural layers clean and lets the audit trail / stable error codes live next to the override-coercion + completion-evidence rules (one inspection point). Locked by `StaffRouteMismatchTests` (4 cases — flag=False + WAITING_CUSTOMER_APPROVAL target = 400; flag=True + WAITING_MANAGER_REVIEW target = 400). | Batch 11 + `backend/tickets/state_machine.py::apply_transition` + PM Q5 |
| 2026-05-17 | **BM rejection of a staff completion (`WAITING_MANAGER_REVIEW → IN_PROGRESS`) requires a note** — two-layer defence: serializer 400 with `{"note": [...]}` field error + state-machine `TransitionError(code="rejection_note_required")` for programmatic callers. Mirrors the existing CUSTOMER_USER reject-note rule (`TicketStatusChangeSerializer.validate` at lines 565-572). | Without a note, "back to in-progress" is just a state flip with no operator context — the assigned STAFF has no way to know what needs more work. Two-layer defence catches both HTTP and programmatic callers (Celery, management commands, future webhooks). Stable code mirrors the existing `override_reason_required` shape. Locked by `BMRejectsStaffCompletionTests` (3 sub-cases — BM with note 200; BM without note 400 with field error; programmatic call without note → TransitionError). | Batch 11 + `backend/tickets/state_machine.py::apply_transition` + `backend/tickets/serializers.py::TicketStatusChangeSerializer.validate` + PM Q7 |
| 2026-05-17 | **Completion-evidence rule extended to include `(IN_PROGRESS, WAITING_MANAGER_REVIEW)`** — same Sprint 25C semantic (note OR visible attachment required); same stable error code `completion_evidence_required`. The existing `(IN_PROGRESS, WAITING_CUSTOMER_APPROVAL)` entry stays — STAFF using the configured route (direct to customer) ALSO needs completion evidence. | The "you must show evidence the work happened" rule applies to BOTH routes equally — manager-review-bound or customer-approval-bound. Reusing the existing `COMPLETION_EVIDENCE_TRANSITIONS` set + the existing `_ticket_has_visible_attachment` helper keeps the rule centralised. Sprint 25C invariant preserved + extended. Locked by `StaffCompletionEvidenceTests` (4 sub-cases × 2 target statuses). | Batch 11 + `backend/tickets/state_machine.py::COMPLETION_EVIDENCE_TRANSITIONS` + PM Q6 |
| 2026-05-17 | **New endpoint `GET /api/tickets/<id>/staff-completion-route/`** returns `{"route": "manager_review" \| "customer_approval"}`. STAFF without `TicketStaffAssignment` → 404; CUSTOMER_USER → 404; provider operators in scope (SUPER_ADMIN / COMPANY_ADMIN / BUILDING_MANAGER for the ticket's building) without `?staff_id=<id>` get the conservative `"manager_review"` default; with `?staff_id=<id>` get the resolved route for that STAFF. NOT `allowed_next_statuses` filter. | The frontend completion modal needs to render the correct destination text + submit-button label without inspecting the BSV row directly. Filtering inside `allowed_next_statuses` would have couplied state-machine semantics ("structurally allowed transitions") to policy semantics ("which route is resolved for this STAFF + building") — they should stay distinct. The dedicated endpoint is the smallest auditable contract for the frontend. 404 (not 403) for out-of-scope callers avoids leaking ticket existence. Locked by `StaffCompletionRouteEndpointTests` (7 sub-cases). | Batch 11 + `backend/tickets/views.py::TicketViewSet.staff_completion_route` + PM Q9 |
| 2026-05-17 | **`is_assigned_staff: boolean` added to `TicketDetailSerializer`** as a SerializerMethodField. Computed per-request from `TicketStaffAssignment.objects.filter(ticket=obj, user=user).exists()`. Frontend uses this directly to decide whether to render the STAFF "Complete work" button — no separate API call needed. | The frontend modal needs to know whether the current viewer is assigned to the ticket WITHOUT inspecting the `assigned_staff` array on every render. Embedding a single boolean on the detail payload is the smallest contract that supports the gate (`STAFF + IN_PROGRESS + is_assigned_staff`) without requiring a list scan. The backend gate enforces the same condition on the transition (defence in depth — the boolean is a UX hint, not a security boundary). | Batch 11 + `backend/tickets/serializers.py::TicketDetailSerializer.get_is_assigned_staff` |
| 2026-05-17 | **`H-5` invariant preserved structurally**: STAFF has NO entry in `(WAITING_CUSTOMER_APPROVAL → APPROVED|REJECTED)` — STAFF still cannot drive the customer-decision transition. The new Batch 11 STAFF transitions (`IN_PROGRESS → WAITING_MANAGER_REVIEW` and `IN_PROGRESS → WAITING_CUSTOMER_APPROVAL`) are "STAFF marking own work done", NOT "approving customer completion". Matrix H-5 row clarified in this commit. | The H-5 floor is the customer-decision lock; the Batch 11 widening is a STAFF-completion lock (different verb). Without the wording clarification a future audit could read the matrix H-5 row + the new transitions and think they conflict — they don't. Lock the distinction explicitly. Regression-locked by `StaffCannotApproveCustomerCompletionTests` (existing H-5 lock) + `StaffCompletionTransitionStructuralTests` (asserts STAFF role IS in the two new outbound IN_PROGRESS transitions). | Batch 11 + `docs/architecture/sprint-27-rbac-matrix.md` §3 row H-5 + `backend/tickets/tests/test_sprint28_staff_completion.py::StaffCannotApproveCustomerCompletionTests` |
| 2026-05-17 | **NO new `osius.*` permission keys for Batch 11.** The `BuildingStaffVisibility.staff_completion_routes_to_customer` field is the source of truth; routing-flag check + `SCOPE_STAFF_ASSIGNED` membership check live in the state machine. | Same pattern as Batch 10 (`visibility_level` — no new osius key). Master plan §2 "do not invent parallel keys when an existing surface expresses the same scope" extends in spirit. The model field + state-machine policy is one inspection point; adding `osius.staff.complete_work` or similar would fragment the vocabulary + require parallel resolver branches in `permissions_v2.py`. | Batch 11 + `backend/tickets/state_machine.py` + PM Q6 |
| 2026-05-17 | **Completion modal is an inline card mirroring the Sprint 27F-F1 override modal shape** (NOT a floating overlay). Inline attachment upload deferred as remaining UX debt; modal copy directs operator to the existing Attachments card on the page. | Mirrors the page's existing modal pattern (Sprint 27F-F1 override modal) — consistent visual language, smallest-safe addition. Inline attachment upload inside the modal would have required restructuring the existing TicketAttachment uploader (currently a sibling card on the same page) — out of "smallest-safe" scope for Batch 11. The modal still satisfies the `completion_evidence_required` rule because the backend accepts note-only completions; STAFF can upload via the Attachments card BEFORE opening the modal if they want photo evidence too. Documented as remaining UX debt for a future polish batch. | Batch 11 + `frontend/src/pages/TicketDetailPage.tsx` + PM Q12 + frontend agent's report |
| 2026-05-17 | **Batch 10 migration + model `default=BUILDING_READ`** (NOT `ASSIGNED_ONLY`). Existing BSV rows are backfilled to `BUILDING_READ`; programmatic `BuildingStaffVisibility.objects.create(user, building)` without an explicit `visibility_level=` kwarg lands as `BUILDING_READ`. | PM-resolved discrepancy in the user's brief. Pre-Batch-10 semantics: a BSV row's mere existence granted full-building read (`accounts/scoping.py:211-230` original code added every BSV row's `building_id` to the visible set). Defaulting the new column to `ASSIGNED_ONLY` would have silently downgraded every existing BSV-holding STAFF user from B2 to B1 — breaking the demo seed (`seed_demo_data.py` creates BSV rows for Ahmet/Noah expecting B2) and a large surface of existing Sprint 24-28 tests that create BSV rows and assert building-wide STAFF visibility. The `BUILDING_READ` default preserves the existing contract; B1 (`ASSIGNED_ONLY`) becomes a NEW opt-in per-row downgrade. Locked by `StaffVisibilityLevelDefaultTests`. | Batch 10 + `backend/buildings/models.py::BuildingStaffVisibility.VisibilityLevel` + `backend/buildings/migrations/0003_buildingstaffvisibility_visibility_level.py` + PM Q2 |
| 2026-05-17 | **B1 (`ASSIGNED_ONLY`) on a BSV row is a NEW per-row downgrade semantic** — recognise STAFF user at building (so `_validate_target_staff` in `views_staff_assignments.py` still treats them as a valid direct-assignment target) but do NOT widen visibility beyond `TicketStaffAssignment`. | The master plan literally says "Extend `BuildingStaffVisibility` with a per-row permission level" — a per-row level only makes sense WITHIN a row. Interpreting B1 as "no BSV row" would have made the new column meaningless. The split lets admins keep STAFF assignable as a direct-assignment target while limiting what tickets they see — supports the spec §6 "single granular permission without promoting global role" pattern. Locked by `StaffB1AssignedOnlyTests` + `StaffAssignmentTargetValidationUnchangedTests`. | Batch 10 + `backend/accounts/scoping.py` STAFF branch + PM Q3 |
| 2026-05-17 | **H-4 floor preserved structurally** — the `Q(_assigned=True)` branch in `scope_tickets_for` STAFF branch is untouched; STAFF with a `TicketStaffAssignment` row ALWAYS sees the assigned ticket, regardless of `visibility_level` (or even absence of a BSV row entirely). | Matrix invariant H-4: STAFF always sees work assigned to them — cannot be removed. The `_assigned=True` clause has no toggle. The new `visibility_level` field only narrows the BUILDING-WIDE-visible set; it never narrows the assigned-ticket-visible set. Finally has dedicated regression-lock coverage via `StaffH4FloorTests` (2 cases: no-BSV-row + `ASSIGNED_ONLY`-BSV-row both still see the assigned ticket) — closes the doc-drift previously noted in audit row 25. | Batch 10 + `backend/accounts/scoping.py` STAFF branch + `backend/tickets/tests/test_sprint28_staff_building_granularity.py::StaffH4FloorTests` |
| 2026-05-17 | **NO new `osius.*` permission keys.** `BuildingStaffVisibility.visibility_level` is the single source of truth; checked directly in `accounts/scoping.py` and `tickets/views.py::assign`. | Master plan §2 hard rule "do not rename `osius.*`" extends in spirit to "do not invent parallel keys when an existing surface expresses the same scope". Adding `osius.staff.view_building_tickets` + `osius.staff.assign_tickets` would have fragmented the permission vocabulary (their resolvers would just read the same column), required parallel narrowing in `permissions_v2.py` for COMPANY_ADMIN per the Sprint 27D pattern, and forced a parallel admin UI surface. Model-field-as-truth keeps the surface area minimal and auditable. | Batch 10 + `backend/buildings/models.py` + PM Q6 |
| 2026-05-17 | **Multi-staff M:N `TicketStaffAssignment` endpoint (`POST/DELETE /api/tickets/<id>/staff-assignments/`) stays admin-only.** STAFF with B3 still receives 403 from `views_staff_assignments.py::_gate_actor`. | The spec phrase "B3 = building-wide read + assign" maps to the BM-assign verb (single `Ticket.assigned_to` FK — what the user sees as "manager of this ticket"). The multi-staff M:N is a provider-admin orchestration surface (who is dispatched to do the work); letting STAFF self-add or remove peers would fragment the dispatch model and interact with `assignable-staff` eligibility in ways no spec line asks for. Document the distinction explicitly in `_gate_actor`'s docstring. Locked by `StaffStaffAssignmentsEndpointUnchangedForStaffTests::test_b3_staff_cannot_use_multi_staff_endpoint`. | Batch 10 + `backend/tickets/views_staff_assignments.py::_gate_actor` (intentionally UNCHANGED) + PM Q5 |
| 2026-05-17 | **`TicketAssignSerializer.validate` mirror-widened** alongside the view-layer gate. Both layers now share the same `BuildingStaffVisibility.visibility_level=BUILDING_READ_AND_ASSIGN` check for STAFF actors. | Necessary deviation from the literal PM brief. The Sprint 28 Batch 2 fix added an explicit STAFF rejection at the serializer level (`backend/tickets/serializers.py:626`); keeping that rejection in place would have made the B3 → 200 path impossible because `is_valid()` would 400 before the view's `save()` could fire. The serializer comment block frames its role as "defence in depth for future call-sites that bypass the view", which means the rule must hold on both layers — not that the serializer must be stricter. Audit row 26 was updated to "PARTIAL": view + serializer halves now consistent; a deeper boolean-edge-case audit of the serializer remains a follow-up. | Batch 10 + `backend/tickets/serializers.py::TicketAssignSerializer.validate` + Backend agent's documented deviation |
| 2026-05-17 | **`building_ids_for(STAFF)` returns ALL BSV building_ids regardless of `visibility_level`.** A STAFF user with `ASSIGNED_ONLY` on a building still sees that building in selectors and the building list endpoint. The narrowing applies only to the ticket-level scope (`scope_tickets_for`). | Asymmetric on purpose: the building dropdown needs to surface every building where STAFF is recognised (so admins can direct-assign them), but the ticket-visible set must respect the per-row level. Symmetric narrowing would have removed `ASSIGNED_ONLY` buildings from the dropdown entirely, breaking the admin direct-assign flow. Documented in the helper's docstring. Frontend MUST NOT pre-filter the building dropdown on the client either — locked by an inline comment in `frontend/src/api/types.ts`. | Batch 10 + `backend/accounts/scoping.py::building_ids_for` STAFF branch |
| 2026-05-17 | **`updateStaffVisibility` frontend API helper refactored from `(userId, buildingId, canRequestAssignment: boolean)` to `(userId, buildingId, patch: StaffVisibilityPatch)`** where `StaffVisibilityPatch = { can_request_assignment?: boolean; visibility_level?: StaffVisibilityLevel }`. | Two writable fields on the same PATCH endpoint; the old positional-boolean signature would have forced every caller to resend the other field on every PATCH (race risk + clobber risk if two admins edit concurrently). The partial-patch shape sends only the mutated field. Only one caller exists (`UserFormPage`); both BSV row event handlers were updated in the same edit. | Batch 10 + `frontend/src/api/admin.ts::updateStaffVisibility` + `frontend/src/pages/admin/UserFormPage.tsx` |
| 2026-05-17 | **"Assigned to you" visual prioritisation = badge only (sort-first parked).** STAFF rows on the dashboard ticket table where `ticket.assigned_to === me.id` get a small "Assigned to you" / "Toegewezen aan jou" badge in the desktop subject cell and mobile ticket card. No sort-first reordering. | The Batch 10 brief required "visually prioritised in the list UI (sort first or marked differently)". Badge is the smallest-safe surface. Sort-first would require role-gated reordering of a shared list (the same dashboard table renders for non-STAFF roles where the sort would be wrong), introducing either a backend sort hint or client-side role-conditional reorder that's larger than this batch warrants. Badge testids `ticket-row-assigned-to-you` + `ticket-card-assigned-to-you` lock the contract; sort-first is documented remaining UX debt. **Badge does NOT honour multi-staff M:N** (fires only on legacy `assigned_to`) — M:N check requires per-row staff-assignments fetch and was deferred. | Batch 10 + `frontend/src/pages/DashboardPage.tsx` + PM Q8 |
| 2026-05-17 | **Batch 9 dashboard sections render side-by-side at viewports ≥ 1400px and stack at narrower widths** via a single CSS Grid wrapper `<div className="dashboard-two-col">` containing the two top-level `<section>`s. The grid declaration is `grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); align-items: start;` inside a `@media (min-width: 1400px)` block; default `grid-template-columns: 1fr` for narrow viewports. The wrapper adds 24px gap. `minmax(0, 1fr)` is load-bearing — it prevents the inner Tickets recent-tickets table from pushing its column wider than 50% of viewport. No JSX content edits inside either section. | Master plan §6 Batch 9 mandates "two top-level sections side by side: Tickets and Extra Work". A first implementation pass stacked them vertically (incorrectly arguing the Tickets inner table would not fit a half-column) and that deviation was rejected as an acceptance-blocking issue. The correct fix is a CSS Grid wrapper at the 1400px breakpoint with `minmax(0, 1fr)` to constrain the Tickets column without altering inner content. Breakpoint chosen at 1400px (rather than 1100px or 1280px) so the Tickets section's own inner `.dash-grid` `1fr + 340px` split — which collapses at its own 1100px breakpoint — keeps room to breathe inside the half-viewport column. Existing Tickets functionality (KPIs, filters, recent-tickets table, mobile cards, pagination, status breakdown, focus list, by-building card) unchanged. Locked by Playwright spec assertions on the four `data-testid` wrappers + visual verification that the side-by-side layout activates at the breakpoint. | Batch 9 + `frontend/src/pages/DashboardPage.tsx` + `frontend/src/index.css` + `frontend/tests/e2e/sprint28_extra_work_dashboard.spec.ts` |
| 2026-05-17 | **Backend stats endpoints return identical JSON shape for every role.** `scope_extra_work_for(request.user)` is the single source of role branching — the *rows* differ per role, not the *fields*. STAFF naturally gets `{total: 0, by_status: {}, ...}` because the scope helper returns `.none()` for STAFF (MVP — no staff-execution surface on EW yet). Frontend decides cell emphasis (CUSTOMER_USER awaiting-customer KPI emphasis) and empty-state rendering. | Mirrors the precedent set by `tickets.views.stats` (lines 292-353) which is also role-uniform in shape. Adding backend role branching to the stats response would have fragmented the API contract and forced frontend to handle N response shapes; reusing the existing scope helper is the smallest, most auditable shape that already enforces H-1 / H-2. STAFF empty-state is naturally produced by the scope's `.none()`; no special STAFF case needed in the view. Locked by `ExtraWorkStatsScopeTests` (5 role coverage including STAFF zero-row case) and `ExtraWorkStatsCrossTenantIsolationTests` (H-1 / H-2 lock). | Batch 9 + `backend/extra_work/views.py` + `backend/extra_work/tests/test_sprint28_extra_work_stats.py` |
| 2026-05-17 | **`awaiting_customer_approval` = `status == PRICING_PROPOSED` only** (Option A from PM Q2). NOT additionally OR'd with `proposals__status=SENT` (Option B). | Batch 8's `apply_proposal_transition` auto-advance contract makes the parent EW status the single source of truth for "customer must decide" state: when a Proposal goes DRAFT→SENT, the parent EW auto-advances UNDER_REVIEW→PRICING_PROPOSED inside the same atomic block. Option B would have introduced a JOIN through the proposals reverse-relation, double-counted when both conditions are true (which is the default state by Batch 8 design), and required a `.distinct()` to dedupe. If a future audit surfaces drift between parent EW status and child proposal status, that's a Batch-8 bug to fix in `apply_proposal_transition` — not something the dashboard query should paper over. Locked by `ExtraWorkStatsBucketsTests::test_awaiting_customer_approval_definition`. | Batch 9 + `backend/extra_work/views.py::stats` + PM Q2 |
| 2026-05-17 | **`awaiting_pricing` = `routing_decision="PROPOSAL"` AND `status IN (REQUESTED, UNDER_REVIEW)`.** Rows that already reached PRICING_PROPOSED roll forward into `awaiting_customer_approval`. | These are the rows in the **operator action queue** — the operator needs to either build a Proposal (Batch 8) or move the request through review first. Once PRICING_PROPOSED is reached, the action moves to the customer. Definition deliberately excludes routing="INSTANT" rows (those skip pricing entirely via Batch 7 instant-ticket spawn). Locked by `ExtraWorkStatsBucketsTests::test_awaiting_pricing_definition`. | Batch 9 + `backend/extra_work/views.py::stats` + PM Q2 |
| 2026-05-17 | **Two module-level constants** `EXTRA_WORK_TERMINAL_STATUSES = ("CUSTOMER_APPROVED", "CUSTOMER_REJECTED", "CANCELLED")` and `EXTRA_WORK_AWAITING_PRICING_STATUSES = ("REQUESTED", "UNDER_REVIEW")` shared between both new actions in `backend/extra_work/views.py`. String literals (not enum accessors) to match the precedent in `tickets.views`. | Keeps bucket semantics in one place — if a future product change adds a new terminal status, both actions update together. String literals avoid an unnecessary import of `ExtraWorkStatus` into the view module and match the `tickets.views.stats` style at lines 299-320. The test module still imports the enums for fixture seeding so name-drift is caught structurally. | Batch 9 + `backend/extra_work/views.py` |
| 2026-05-17 | **Extra Work status i18n labels added to `dashboard.json`** under `extra_work_status_*` keys (local-to-namespace) rather than centralised in `common.json`. Six labels: REQUESTED / UNDER_REVIEW / PRICING_PROPOSED / CUSTOMER_APPROVED / CUSTOMER_REJECTED / CANCELLED in EN + NL. | Avoids a cross-namespace refactor in Batch 9. The labels are currently only consumed by the dashboard status-breakdown card; centralising prematurely would have forced a broader i18n bundle review for zero functional gain. A later polish batch can consolidate under `common.extra_work_status.*` when more pages need the same labels (e.g. when the proposal builder UI lands). EN/NL parity verified via `diff <(grep ...) <(grep ...)`. | Batch 9 + `frontend/src/i18n/{en,nl}/dashboard.json` |
| 2026-05-17 | **API helper Option A**: typed `getExtraWorkStats()` and `getExtraWorkStatsByBuilding()` helpers in `frontend/src/api/extraWork.ts`, NOT inline `api.get<>` calls in `DashboardPage.tsx`. | Matches the existing extra-work helper pattern in the same file (`getExtraWork`, `listExtraWork`, etc.). Keeps the page component free of URL string literals; gives the dashboard symmetric imports per domain. Marginal duplication with the inline ticket-stats pattern is acceptable — tickets is the older domain and refactoring its dashboard call sites is out of scope for Batch 9. | Batch 9 + `frontend/src/api/extraWork.ts` + PM Q2 |
| 2026-05-17 | **`data-testid` contracts locked for the dashboard**: `dashboard-tickets-section`, `dashboard-extra-work-section`, `dashboard-extra-work-kpi-awaiting-customer`, `dashboard-extra-work-section-empty`. | Stable testids decouple the Playwright spec from i18n string drift + class-name churn. Provider/customer/staff role behaviour is asserted via the testid presence/absence rather than counting cells (which would depend on seed data). The 4 testids cover the 3 Playwright cases the brief asks for (provider sees both sections; CUSTOMER_USER sees awaiting-customer emphasis; STAFF sees empty state). | Batch 9 + `frontend/src/pages/DashboardPage.tsx` + `frontend/tests/e2e/sprint28_extra_work_dashboard.spec.ts` |
| 2026-05-17 | **Proposal line field naming = spec names `customer_explanation` + `internal_note`** on the new `ProposalLine` model. The legacy `ExtraWorkPricingLineItem` keeps its `customer_visible_note` / `internal_cost_note` naming. | §10 Open Question 1 default; spec §6 hard rule that `internal_note` MUST never appear on a customer-facing endpoint or PDF. Legacy model is a different concept (provider-built single-line breakdown) and renaming it would be scope creep. Dual-serializer pattern + JSON grep-assert regression-lock in `DualNotePrivacyTests`. | Batch 8 + `backend/extra_work/models.py::ProposalLine` + `backend/extra_work/serializers.py::ProposalLineAdminSerializer`/`ProposalLineCustomerSerializer` |
| 2026-05-17 | **1:N parent→proposals with partial UniqueConstraint blocking parallel open rows.** A single `ExtraWorkRequest` may have at most one `Proposal` with `status IN (DRAFT, SENT)` at a time (named `uniq_proposal_open_per_request`, `condition=Q(status__in=["DRAFT","SENT"])`). After CUSTOMER_REJECTED / CANCELLED the operator creates a fresh DRAFT proposal — there is NO `CUSTOMER_REJECTED → DRAFT` transition on the existing row. | Existing parent EW state machine already supports `CUSTOMER_REJECTED → UNDER_REVIEW` (re-pricing); modelling proposals 1:N preserves history (old rejected proposal becomes a historical record), avoids destructive edits, and lets the audit trail explain the full negotiation. A 1:1 shape would have forced lossy in-place edits. Locked by `ProposalReSendAfterRejectionTests` + `UniqueOpenProposalTests`. | Batch 8 + `backend/extra_work/models.py::Proposal.Meta.constraints` + PM Q1 (a) |
| 2026-05-17 | **`Ticket.proposal_line` is a NEW nullable FK** (`extra_work.ProposalLine`, `on_delete=SET_NULL`, `related_name="spawned_tickets_for_proposal_line"`) parallel to Batch 7's `Ticket.extra_work_request_item` — NOT a reuse of the cart-line FK. Migration `tickets/0009_ticket_proposal_line.py` (cross-app dependency on `extra_work.0004_proposal_models`). Idempotency check: `Ticket.objects.filter(proposal_line=line).exists()`. | PM Q5 (a) Option A. Reusing the cart-line FK (Option B) would have lost the divergent (unit_price, quantity, customer_explanation) values that a ProposalLine carries — the operator may bill differently than the original cart line; the audit trail must point at the proposal-line that actually drove the ticket. SET_NULL preserves the Ticket if the proposal line is later deleted; spawn-origin history is lost in that case (same trade-off as Batch 7's cart-line FK). Locked by `CustomerApproveSpawnTests`. | Batch 8 + `backend/tickets/models.py::Ticket.proposal_line` + `backend/tickets/migrations/0009_ticket_proposal_line.py` + PM Q5 (a) |
| 2026-05-17 | **`apply_proposal_transition` BYPASSES `extra_work.state_machine.apply_transition` for the parent-EW auto-advance** on send + approve/reject. The bypass writes the parent's `status` field + a fresh `ExtraWorkStatusHistory` row directly inside the proposal-transition's atomic block. | Reusing `apply_transition` would have hit the legacy `pricing_line_items_required` precondition (state_machine.py:272–282) which targets the legacy `ExtraWorkPricingLineItem` flow — the new ProposalLine flow has no such requirement (the Proposal IS the pricing surface). Bypassing keeps both code paths intact: legacy `/pricing-items/` endpoints still validate as before; the proposal flow ships without modifying the legacy precondition. Defensive: parent auto-advance is idempotent (no-op if parent is not in the expected source status). | Batch 8 + `backend/extra_work/proposal_state_machine.py::apply_proposal_transition` + PM Q6 + Q12 |
| 2026-05-17 | **`Proposal.send` rejects when parent EW is in `REQUESTED`** — operator MUST drive `REQUESTED → UNDER_REVIEW` manually via the existing `/transition/` endpoint before sending. HTTP 400 with stable code `proposal_send_requires_under_review`. | Keeps the state-machine narrative coherent: the parent EW transition (REQUESTED→UNDER_REVIEW) is a deliberate operator act that says "I have reviewed the cart and am building a proposal" — collapsing it into the proposal-send action would have written two parent history rows on a single click and obscured the review step. Locked by `ProposalSendAdvancesParentTests::test_proposal_send_rejects_when_parent_is_requested`. | Batch 8 + `backend/extra_work/proposal_state_machine.py::apply_proposal_transition` + PM Q4 (c) / Q6 |
| 2026-05-17 | **Provider-driven SENT → CANCELLED is also coerced to `is_override=True` + `override_reason` required** (provider withdrawing a sent proposal). Same coercion shape as provider-driven SENT → CUSTOMER_APPROVED/REJECTED. | Withdrawing a sent proposal is a significant act — the customer has already seen the pricing and the audit trail must explain why the operator is pulling it back. Mirrors the Sprint 27F-B1 ticket-override pattern + the existing EW provider-driven-customer-decision-is-always-override pattern at state_machine.py:289–304. Locked by `ProviderOverrideTests`. | Batch 8 + `backend/extra_work/proposal_state_machine.py::apply_proposal_transition` + PM Q4 (a) |
| 2026-05-17 | **`is_approved_for_spawn: BooleanField(default=True)` added to `ProposalLine`** as a forward-compat schema slot for the parked per-line approve/reject UX. In Batch 8 nothing flips the column to False, but `spawn_tickets_for_proposal` filters on it so the slot is honoured if a future batch wires up the UI. | Master plan §6 Batch 8 says "one Ticket per approved line"; interpreting as whole-proposal approval is the smallest shape that does not preclude a future per-line split. Reserving the column now means no migration is needed when the UX lands. Locked by `IdempotencyTests::test_lines_with_is_approved_for_spawn_false_do_not_spawn_tickets`. | Batch 8 + `backend/extra_work/models.py::ProposalLine.is_approved_for_spawn` + PM Q2 (b) |
| 2026-05-17 | **`ProposalTimelineEvent.customer_visible: bool` is written at emission time** (not derived from event_type in the serializer). All six emission helpers default to True; the field exists so a future event can suppress visibility without changing the serializer layer. Customer-facing timeline serializer applies `.filter(customer_visible=True)` AND omits `metadata` entirely (where the override_reason text would otherwise leak via `ADMIN_OVERRIDDEN` events). | Field-level visibility flag avoids coupling the customer serializer to event_type enum semantics — adding a new event_type doesn't accidentally leak it to the customer feed. The `metadata`-strip is the second line of defence: even if `customer_visible` is mis-set on a row, the customer never sees the provider-only context payload. Locked by `TimelineEmissionTests::test_customer_timeline_serializer_omits_metadata`. | Batch 8 + `backend/extra_work/models.py::ProposalTimelineEvent.customer_visible` + `backend/extra_work/serializers.py::ProposalTimelineEventCustomerSerializer` + PM Q3 (b) / (c) |
| 2026-05-17 | **H-11 audit registration split**: `Proposal` + `ProposalLine` ARE registered for full-CRUD in `audit/signals.py`. `ProposalStatusHistory` + `ProposalTimelineEvent` are deliberately NOT registered. The history rows ARE the workflow-override audit trail (they carry `is_override` + `override_reason` themselves); the timeline event row IS the operator-facing change log. Adding them to the generic AuditLog would double-write the same fact. Regression-locked by `ProposalTimelineEventNotAuditedTests`. | Matrix invariant H-11: workflow override (per-transition) and permission override (per-access-row) are separate concepts; the generic AuditLog tracks permission/scope/role/state-model CRUD, the `*StatusHistory` rows track workflow transitions. Mirrors the Sprint 27F-B1 ticket precedent that does not register `TicketStatusHistory` for AuditLog. | Batch 8 + `backend/audit/signals.py::_connect` + `backend/audit/tests/test_sprint28_proposal_audit.py::ProposalTimelineEventNotAuditedTests` + PM Q8 |
| 2026-05-17 | **Reuse existing `osius.ticket.view_building` for all provider-side building-scope checks on Proposal endpoints.** No new `osius.*` permission key introduced. | Master plan §2 hard rule "do not rename `osius.*`" extends in spirit to "do not invent parallel keys when an existing one expresses the same scope". `extra_work.state_machine.py:160–189` already reuses `osius.ticket.view_building` for EW transitions; the proposal builder is administratively a subset of the existing Extra Work surface. A new key like `osius.extra_work.build_proposal` would fragment the provider-side scope vocabulary for zero functional gain. Locked by all scope tests across the 47-test Batch 8 footprint. | Batch 8 + `backend/extra_work/proposal_state_machine.py::_provider_in_building_scope` + PM Q10 (c) |
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
