# Osius — Gap-Closing Sprint Checklist

**Purpose.** The living plan to close every remaining gap between the
system and the Ramazan transcripts + Source of Truth, ending with a
premium UI/UX polish. **CC updates `## NOW` / `## NEXT` / `## SHIPPED`
for a sprint as part of that sprint's own commit(s)** — not in a later
docs-only pass — so this file always reflects where we actually are.

---

## How to maintain this file (read this before editing anything below)

- **`## NOW`** is rewritten every sprint — replace it, don't append to it.
  It should stay a paragraph or a few bullets: current branch, the last
  shipped PR on `main`, what's in flight, and the immediate next sprint.
- **`## NEXT`** is ONE ordered queue, re-ordered whenever priorities
  change. Add a newly-found item here as soon as it's found — don't let
  it wait for a dedicated audit sprint. Remove an item once its sprint
  starts (it moves into `## NOW`) or ships (it moves into `## SHIPPED`).
- **`## SHIPPED`** is append-only: one line per merged PR, newest first.
  Never edit a historical line's wording once it's written — if a line
  turns out to be inaccurate, add a corrected note rather than rewriting
  it (see the #115 entry below for the pattern).
- Everything after the second `---` is a **frozen appendix**, or has been
  moved to `docs/archive/` — not maintained, not current truth. Only edit
  it to move MORE material out, not to update its content.
- **This file drifted out of date twice** before Sprint 122.1 restructured
  it (see `docs/archive/2026-06-sprints/` for what moved out and why) —
  in both cases because nothing *required* the update to happen. CLAUDE.md
  §8 now has a standing rule for this: a sprint does not close without
  updating NOW/NEXT/SHIPPED in that same branch. Don't let it drift a
  third time.
- **A PR cannot cite its own number.** The `## SHIPPED` line for a merged PR
  is therefore appended by the FIRST commit of the NEXT branch, not by the
  PR it describes. A one-PR lag is by design; a two-PR lag is drift. (This
  is what happened to #119 — Sprints 123 and 124 correctly declined to
  invent a number, and the entry then had nowhere to land until this
  docs-only close-out.)
- **Cross-references into `## NEXT` cite the item by NAME, never by
  number.** `## NEXT` renumbers whenever an item ships, which silently
  breaks every numeric pointer into it.

---

## Conventions (apply to every sprint / CC prompt)
- Backend is the business source of truth; **verify, don't assume**; never invent endpoints.
- **Never stage** `docs/transkript*` or their `:Zone.Identifier`. Stage commits by **explicit path**.
- nl + en i18n in lockstep (Dutch primary); every referenced i18n key must resolve (no raw keys on screen).
- ESLint baseline = **48** (46 errors, 2 warnings): add **no** new violations; **never** a synchronous setState in an effect body; for prop-derived state, **key the component by id** (no resync useEffect). (Sprint 115 removed an unused hook, `useEffectivePermissions.ts`, that carried one violation — baseline dropped 49 → 48; still 48 as of Sprint 122.)
- **PR cadence (corrected 2026-07-27 — the old "PR per sprint" line was stale):** several sprints now land on ONE shared branch and the owner opens ONE PR after the last of them (Sprints 115–119 → PR #115; Sprints 122–124 are following the same pattern on `feat/sprint-122`). CI (+ Codex review) still gates that one PR when it opens. Migrations stay additive + back-compat regardless of when the PR opens.
- Each prompt starts with a sync + a grep GUARD proving the right base, captures the ESLint baseline, applies any new migration to the dev DB before a FE smoke, and ends with an adversarial self-review. Screenshots/smokes via **token-inject** (the e2e login form is flaky).
- Co-author trailer on commits: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` (the old line here named a different model — verify the current one in `CLAUDE.md` before reusing this, it has changed before).

---

## NOW

**Branch:** `fix/sprint-137-ramazan-round-1` — Sprint 137 items 1-7, the
Sprint 138 round-2 items, the Sprint 139 round-3 consistency fixes, and
the Sprint 140 round-4 completion of them, and the Sprint 141 round-5
failure-path audit; each round found by the owner or the PM verifying the
previous one before merging. Cut from `main`@`751bb8d`. **Still ONE PR**; nothing
merges in between, and CC does not open PRs — the owner does.

**Last shipped PR on `main`: #126** — Sprints 133/134/135/136. Its
SHIPPED line was appended by this branch.

**Round 1 (Sprint 137, commits `8399028` + `82397bb`):** multi-attachment
tickets; archived prices hidden by default; the "copy from defaults
duplicates" report resolved as NOT a duplication bug (code analysis, the
owner verifies on crmtest); the customer-pricing category drill-down;
the Extra Work form's real catalog-category filter; orderable
`CustomerCustomPrice` lines; and iOS-style bulk edit mode on three lists.

**Round 2 (Sprint 138) — the theme the owner named: the interface
offered actions that cannot succeed, or carried machinery for states
nobody needs to manage. Removing an impossible button beats making it
work.**

- **§1 Services — Delete only when it can actually work.** The catalog
  offered Delete on every row. For a priced service it ALWAYS failed,
  and the 400 named prices the operator believed he had already deleted
  — they were archived, and archived rows still PROTECT. That is the
  "Deleted 0 service(s), 1 failed" screen. `Service` now carries
  `has_price_rows`, from ONE `Exists` subquery annotated on the list
  queryset (no per-row query). A referenced service offers
  **Deactiveren / Activeren** instead of Delete, single and bulk; an
  unreferenced one keeps a Delete that works. The 400 survives as a
  server-side backstop, reworded to say archived prices block deletion
  too and to point at deactivation instead of the dead end it used to
  recommend.
- **§2 Categories — archive → empty → delete.** Archiving a category now
  cascades to its services in ONE transaction
  (`POST /api/services/categories/<id>/archive/`), because
  `Service.category` is NOT nullable and leaving a retired category's
  services active would strand them: live in every picker, invisible in
  the category UI. Unarchive restores the CATEGORY ONLY and reports how
  many services stayed archived, so nobody assumes a full restore.
  Services can be **moved between categories in bulk** from the Services
  edit mode — the mechanism that empties a category, with archived
  targets opt-in. An EMPTY category (active or archived) offers Delete;
  a non-empty one never does, and the per-row service count is on the
  list so the operator can see WHY without clicking in.
- **§3 Archived PRICES are read-only, by construction.** With "Show
  archived" on, an archived price could be selected and archived AGAIN:
  the backend returned 204 (it was already inactive), the row vanished,
  and it was back on reload — a success reported for something that did
  not happen. Archived price rows now render quiet, carry NO checkbox,
  are not selectable and have no row actions, so the second archive
  cannot be requested at all. Select-all covers ACTIVE rows only and the
  count says so. No restore flow, no permanent delete, no "skipped"
  reporting was built — deliberately. **PRICES only:** archived
  CATEGORIES and SERVICES are catalog rows, not audit records, and keep
  their actions per §1/§2.
- **§4 The archived toggle reflects state.** It read "Show archived"
  whether or not archived rows were showing, so hiding them meant
  pressing a button labelled "show". It now toggles its label, and the
  list itself says when archived rows are included.
- **§5 Copy-from-defaults groups by category.** One flat scrolling list
  became per-category groups with a per-category select-all that covers
  every service in the category — including rows the text filter is
  hiding — so "copy this whole category" is one click. The endpoint is
  unchanged; the created/skipped summary it already returned is still
  surfaced.
- **§6 The Extra Work filter bar, MEASURED not eyeballed.** Nine
  controls wrapped into three ragged rows with the cascade hint floating
  beside them. Each filter is now a compact label-over-control stack,
  bottom-aligned, growing to share its row so the right edge is flush;
  the hint moved to one line beneath the controls it describes (and onto
  each disabled control's `title`). Measured with Playwright against the
  real built page: **1280px → 2 rows (was 3), 0px horizontal page
  overflow, no inner scroll; 1440px → 2 rows; 1024px → 3 rows, still 0px
  overflow.** A literal single line is geometrically impossible here:
  the content column is 966px at 1280px viewport, and nine controls at a
  usable 140px plus 12px gaps need ~1356px. Getting to one line would
  mean hiding filters behind a disclosure, which risks concealing an
  ACTIVE filter — the exact class of defect this sprint exists to
  remove — so it was not done. Recorded in `## NEXT`.

**Round 3 (Sprint 139) — four consistency defects found on crmtest.**
The same underlying idea was implemented differently in different
places; these make them agree.

- **§1 Deactivating a service now behaves like archiving a price.** The
  customer pricing list hid archived rows behind a toggle while the
  Services catalog kept deactivated rows on screen forever marked
  "Inactive" — two lists, two behaviours, one idea. Inactive services
  (and inactive Units, which had the same shape) are now HIDDEN by
  default and revealed by the same show/hide toggle with a
  state-reflecting label, rendered with the same quiet row treatment
  (`.list-row-archived`, generalised from the price-only class). Reuses
  the endpoints' EXISTING `?is_active=` param — no second mechanism.
  The Deactiveren / Activeren actions are unchanged; an inactive row
  stays reachable through the toggle, and its detail panel still opens
  so it can be reactivated.
- **§2 Result banners auto-dismiss — but only the SUCCESSFUL ones.**
  "Deleted 1 service(s)." used to sit on the page indefinitely. Success
  results now go through the app's existing `ToastProvider`
  (`useToast().push`), whose defaults already encode the right rule:
  4s for success, and **sticky for errors**. Failure and partial-failure
  results deliberately stay as in-page alerts, because they name the
  rows the operator still has to deal with — those must not disappear
  on a timer. No second toast pattern was introduced.
- **§3 One category-grouped picker, used three times.** The bulk
  price-adjust modals (catalog defaults, and customer contract prices)
  were still flat scrolling lists while copy-from-defaults had been
  grouped in Sprint 138 §5, so the same catalog looked different
  depending on which modal you opened. Extracted
  `CategoryGroupedPicker` + `buildPickerGroups` and moved all THREE onto
  it, including the "select-all covers rows the filter is hiding" rule
  and the real-total count in each group header. The grouping helper
  lives in `lib/pickerGroups.ts` rather than beside the component,
  because `react-refresh/only-export-components` rejects a component
  module that also exports plain functions.
- **§4 The company dropdown filters the lists.** It previously only
  disambiguated which company a NEW row belonged to (Sprint 135), which
  is not what an operator expects from a dropdown above a list. It now
  also narrows the Services and Units lists, via `?company=` — already
  supported by the Units endpoint, added to the Service endpoint this
  round. It is applied BEFORE `filter_services_for`, so it can only
  narrow: a COMPANY_ADMIN naming another company's id gets an empty
  list, never that company's catalog (asserted). Categories are global
  and unaffected; the page already said so on the Categories tab, and
  the Services/Units tabs now say what the selector DOES do there.

**Round 4 (Sprint 140) — finishing round 3 properly.** The PM's
verification of `649b854` found Sprint 139 §1 incomplete in four places,
all one shape: **the list contradicted its own toggle.** Fixed by
construction rather than site by site.

- **§1/§2 The Services mutation paths bypassed the filter, and the
  helper could drop a row but never bring one back.** Create and edit
  wrote straight into `services`, so creating a service with Active
  unticked (or unticking it in the edit modal) left a row on screen that
  the toggle claimed to hide. Worse, `applyServiceUpdates` mapped over
  the rows already displayed: once a deactivated row had LEFT the list,
  pressing **Activeren** PATCHed successfully and the row never came
  back. Every local-merge variant has that hole in one direction or the
  other, so local merging was abandoned — every mutation now re-reads
  through `refreshCatalogRows()`, which honours the archived toggle and
  the company filter, and refetches category counts alongside (a
  create, delete or category change moves the `service_count` that gates
  Delete on the Categories tab).

  Chosen over a merge-and-insert helper deliberately: the server orders
  services by `category__name, name, id`, while the client insert it
  would have replaced sorted by `name` alone — the two ALREADY
  disagreed, so re-implementing insertion would have cemented a second,
  wrong ordering rule. One round-trip on an admin page is the cheaper
  correctness, and there is no flicker (single `setState`, loading bar
  untouched, no intermediate empty render).
- **§3 The Units tab had received none of Sprint 139's treatment.** Its
  create and edit paths were bare `setUnits` with no helper in the file
  at all — and since the edit modal's Active toggle was the only way to
  deactivate a unit, deactivating one left it sitting in a list that
  claimed to hide inactive rows. It now has the same `refreshUnits()`
  treatment on create, edit, delete and bulk delete. It also gained the
  **Activeren / Deactiveren** action the Services detail panel has:
  Sprint 139 reused `services.inactive_included_note`, which tells the
  operator inactive rows can be "reactivated from their detail panel",
  and that panel had no such control. Fixed by adding the control, NOT
  by softening the sentence.
- **§4 The customer pricing page had the mirror-image bug, in both
  directions, at more sites than the review flagged.** Bulk-adjust and
  copy-from-defaults refetched without `{ includeArchived: showArchived }`
  — but so did create, edit, single delete and bulk archive, each in its
  own way. With the toggle OFF, creating or editing a row to inactive
  inserted or kept a row that should not be listed; with the toggle ON,
  deleting or bulk-archiving REMOVED a row from view even though an
  archived row is precisely what that toggle exists to show. All six now
  go through one `refreshPricingRows()`; only the load effect and that
  helper write the price lists at all.
- **§5** One stale comment corrected: the Units endpoint docstring still
  claimed the admin surface requests the unfiltered list, which stopped
  being true in Sprint 139 §1.

No backend behaviour changed this round (one docstring), so the Django
suite was deliberately NOT run — CI's parallel full regression on the PR
is the gate, and this box has one core. The DEV database was one
migration behind HEAD and was brought to `extra_work.0022`; crmtest was
already there and was not touched.

**Round 5 (Sprint 141) — the failure paths Round 4 never audited.**
Round 4's fixes were correct and its five defects are genuinely gone,
but converting thirteen synchronous state updates into
`await refreshX()` was done without asking what happens when the REFETCH
throws. That introduced two new classes, both caught in review.

- **§1 Five bulk handlers could wedge until a page reload.** Each placed
  `await refreshX()` before the lines that reset the busy flag and closed
  the dialog, with no `finally`. `ConfirmDialog` invokes the handler as
  `void onConfirm()` — the rejection is swallowed — and disables BOTH
  Cancel and Confirm while `busy`, so the dialog went inert. The
  hand-rolled move modal was worse: no Esc, no backdrop click, Cancel
  disabled on `moveBusy`.
- **§2 A committed write could be reported as a failure.** Create and
  edit ran the refetch inside the form's existing `try`, so a re-read
  failure set a FORM error and left the modal open. Worst on the pricing
  page: `CustomerServicePrice` / `CustomerCustomPrice` have NO uniqueness
  constraint — multiple active rows per (customer, service) are legal by
  design and `resolve_price` disambiguates by `valid_from` — so an
  operator retrying after a false failure would create a REAL duplicate
  active price row.
- **The fix, applied once rather than at thirteen call sites.** All three
  refetch helpers are now non-throwing by contract: they catch, leave the
  list stale, and surface a page-level (not form-level) message saying
  the change was saved but the list could not be refreshed. Per-site
  `try/finally` would have fixed §1 only — §2 needs the rejection to stop
  reaching the form's `catch`, so every site would have needed BOTH.
  Round 4's defect was precisely that the correct guard was written once
  and omitted everywhere else; putting it in the helper makes omission
  impossible. The now-redundant wrapper at the cascade-archive was
  removed.
- Three state writes that sat AFTER the refetch were moved BEFORE it, so
  they no longer depend on a network call that is allowed to fail:
  the two detail-panel selections, and the copy-from-defaults
  created/skipped summary that the comment above it promises to keep
  visible.

**Standing rule recorded from this round:** whenever a synchronous state
update becomes an `await`, audit the throw path — which flag stays set,
which modal stays open, what the user is told, and what a retry does.
Round 4's adversarial review covered filter-correctness thoroughly and
failure paths not at all, which is exactly where its defects were.

FE gate: tsc clean, ESLint **48** (46 errors, 2 warnings — baseline held,
no new violations, no new `eslint-disable`), build OK. nl/en verified
identical across all 11 namespaces, every referenced key resolving in
both locales.

Production hardening remains **postponed at the owner's instruction** — it
needs his own inputs (SMTP credentials, a Sentry DSN, the real production
`PLATFORM_BRAND_SLUG`); see `## NEXT`. Off-site backups are BUILT but not
yet running — also its own `## NEXT` item.

---

## NEXT

Single ordered queue — replaces the four lists this used to be spread
across ("Owner's forward queue", "Deferred / undecided items", "Standing
milestones", "Deferred"). All four are now retired; every genuinely-open
item from them lives here, and every already-shipped or already-decided
item has moved to `## SHIPPED` or been resolved below instead.

1. **SUPER_ADMIN "My Work" page content** — what should an SA see on a
   "my work" surface? An SA creates little of their own work; the
   concept today is admin-scoped. Awaiting the owner's definition before
   anything is built.
2. **Dashboard "Mijn werk" section purpose** — clarify whether the chip
   row means "items I created" (current behaviour) or a broader "what
   needs me" queue, and whether it should differ per role. Awaiting
   owner direction.
3. **Fixing & Auditing Sprint** — gated on Ramazan's full side-by-side
   review landing (his own commitment, not yet delivered as of
   2026-07-27). Scope once it lands: incorporate whatever further changes
   Ramazan + father want; pin down **RF-7** (the Extra Work
   pricing-area "big tabs" element he wants changed — location confirmed,
   exact element still to be pinpointed — see the appendix below); design
   + build the **Department + Event** section in person with Ramazan and
   father (the `Department` MODEL itself already exists and shipped in
   Sprint 127 — see item 6 — this item is about the broader in-person
   UI/workflow design, not the label model); a full codebase audit
   (bugs / dead code / inconsistencies, confirm each shipped feature
   behaves as intended); reconcile this checklist against the real
   codebase once the audit lands.
4. **Mobile responsiveness** — gated on Ramazan's review landing (#3).
5. **Light/advanced mode split** — gated on Ramazan's review. Owner
   decision: this is an **architectural** decision to be settled BEFORE
   the Department + Work Type features are built, not a later styling pass.
6. **Department + Work Type** — designed in person with Ramazan and father
   (see #3). The two per-customer label lists + Extra Work tagging +
   filtering shipped (backend Sprint 127, frontend Sprint 128). Of the
   two **Sprint C** follow-ups gated on that tagging (group Extra Work /
   invoices by Customer + Building + Department + Work Type), **both are
   now done**: the **grouped report** — Sprint 131,
   `compute_extra_work_by_department`, summary + numbered-detail CSV/PDF
   export, a customer Reports-tab tree — and **invoice grouping** —
   Sprint 132, `Customer.InvoiceGranularity.PER_BUILDING_DEPARTMENT_
   WORK_TYPE`, plus the Sprint 134 resync fix (`Invoice.granularity`).
   Both shipped to `main` via PR #125 (`## SHIPPED`). Sprint C itself is
   closed; what remains of this item is the BROADER Department + Event UI
   design, still gated on an in-person session with Ramazan and father.
   Naming clarification from the reference implementation:
   **"Event" was never a separate feature** — it is one VALUE in B
   Amsterdam's **Department** list (Algemeen / Event / Member), and the real
   second field is **Work Type** (Eindschoonmaak / Opleverschoonmaak / Bouw
   schoonmaak / Extra werkzaamheden / Overige), not a selectable "event
   type". Department is NOT an org-chart department — it is a sub-client /
   segment of the customer (another customer's are twelve medical practices).
7. **General code refactoring** (clean-up only, **no behaviour change**)
   — owner decision: happens AFTER Department + Work Type ship, not before.
8. **E2E Testing Sprint** — after Fixing & Auditing. Scope: Playwright
    coverage of the critical full-stack flows on the settled
    post-feedback system — auth/login, create ticket + melding, ticket
    lifecycle (staff complete → manager review → customer approval),
    extra-work request → proposal/instant → actual-hours finalize,
    customer pricing (contract / custom / bulk-raise / copy-default),
    notification deep-links. Token-inject pattern (the e2e login form is
    flaky). Green in CI. Ordering rationale (recorded 2026-06-23, still
    the plan): the Fixing & Auditing sprint reshapes the UI, so tests
    written first would be invalidated by those changes.
9. **Frontend Testing Sprint** — after E2E. Component/unit tests for
    high-value frontend logic that lacks coverage: pricing-amount
    display, active-priced-line selection, permission/visibility gating,
    the drill-in people/permissions flows, notification rendering, and
    **the Sprint 129 session-expiry auth flow** (a failed mid-session
    refresh clears `me` + lands on `/login` with the notice; already-on-
    `/login` does not loop; a SUCCESSFUL refresh transparently retries and
    does NOT log out — see `AuthContext` + `api/client.ts::onSessionExpired`).
    That P1 fix shipped in PR **#124** (Sprint 129 — the checklist
    previously miscited this as "#129", conflating the sprint number with
    the PR number; corrected here) verified by review + the FE gates only,
    because no unit runner exists to assert the axios-interceptor
    behaviour. **Sprint 134 already built the interim option this item
    anticipated:** `frontend/tests/e2e/sprint134_axios_timeout.spec.ts`, a
    `page.route`-mocked Playwright e2e covering the client-timeout/
    session-expiry interaction specifically (a permanently-hanging
    refresh and a 401'd refresh both converging on `/login` with the
    notice) — so that one flow is no longer completely uncovered, though
    a real unit-test runner is still the actual ask, and every other flow
    this item lists still has zero coverage. Establish the test runner +
    a CI gate; do not regress the ESLint baseline (48). No frontend
    component/unit test runner exists yet — backend `manage.py test` and
    Playwright e2e are the only test runners today; do not add an
    alternative opportunistically outside this planned sprint (CLAUDE.md §8).
10. **Off-site, encrypted backups — BUILT, NOT RUNNING.** Sprint 134
    built the whole pipeline: `scripts/backup_restic.sh` (one encrypted
    restic snapshot per night covering both a Postgres dump and the
    ENTIRE `backend_media_prod` volume — not just ticket attachments, see
    `docs/operations/backups.md` §1 for the full list of what that volume
    holds), the `scripts/systemd/osius-backup-restic.{service,timer}`
    pair, and a documented restore drill. **None of it has been run.** No
    restic repository has been initialized, no encryption credentials
    generated, no backup has ever actually been taken, and the restore
    drill has never been exercised once. This is the difference between
    "we have backups" and "we have backup CODE" — do not read the code's
    existence as the risk being closed. Blocked solely on the owner
    buying off-site storage (a Hetzner Storage Box or equivalent) and
    provisioning `/etc/osius-backup.env` — see `docs/operations/
    backups.md` §2–3 for the exact steps once storage exists. Until that
    happens, a disk loss is still unrecoverable, exactly as before Sprint
    134.
11. **Production hardening → CD → Sentry.** Needs the owner's OWN input,
    not blocked on engineering: real SMTP credentials, a Sentry account +
    DSN, and the real production OSIUS company slug for
    `PLATFORM_BRAND_SLUG` (see `sot-addendum-b-invoicing.md` §B.9 — if it
    doesn't match, OSIUS's own invoices render unbranded). CD via GitHub
    Actions is otherwise ready to wire up (CI already runs as required PR
    checks). Also standing: TLS, non-root containers (Postgres + media
    backups are now their own item, above). The owner will work through
    these interactively, not as an engineering-only backlog item.
12. **`login.spec.ts`'s "demo card click fills the login form" e2e test
    fails on a clean `main` build** — found while cherry-picking the axios
    timeout fix (Sprint 134) onto this branch. Predates this branch
    entirely: reproduces from `main` alone, with neither `LoginPage.tsx`
    nor `login.spec.ts` touched by anything on it. Clicking
    `[data-testid="demo-card-customer-b3"]` no longer autofills
    `amanda-customer-b-amsterdam@b-amsterdam.demo` into the login form.
    Not investigated or fixed here — recorded so it isn't mistaken for a
    regression on some future branch's e2e run.
13. **`ALLOWED_HOSTS` admits the Docker internal DNS name — an OPTIONAL
    follow-up now available, not a live bug.** This item's previous
    wording was wrong: it claimed the backend container reported
    `(unhealthy)` because the healthcheck hit the `ALLOWED_HOSTS` gate.
    Verified directly against `docker-compose.prod.yml` (Sprint 136): the
    backend healthcheck is a pure TCP SOCKET probe
    (`socket.create_connection(('localhost',8000),2)`), not an HTTP
    request — it never touches Django's request/Host-header pipeline at
    all, so it cannot trip `ALLOWED_HOSTS` regardless of what's in it.
    That was true only BEFORE the TCP probe replaced an earlier HTTP
    probe; the item was written from the stale, pre-swap version, and the
    122.1 restructure carried the stale text forward without
    re-verifying it against the compose file.
    Sprint 134 still did something real, worth keeping: `backend/config/
    settings.py` now unconditionally admits `"backend"` (the Compose
    internal DNS name, in both compose files) to `ALLOWED_HOSTS`. That
    doesn't repair a live failure — there isn't one — it REMOVES the
    reason an HTTP probe would have failed, so switching the compose
    healthcheck from the TCP probe to a real HTTP check (e.g. `curl -H
    "Host: backend" http://localhost:8000/health/live`) is now POSSIBLE,
    upgrading liveness from "gunicorn accepts TCP connections" to
    "gunicorn accepts TCP connections AND Django itself responds 200".
    Nobody has made that switch. See `docs/engineering/deployment.md` §4
    for the full writeup. Optional, not urgent.
14. **`customer_ids[0]` blindness in `MyMeldingenPage` and
    `MyEmployeesPage`.** Same bug `/my/documents` had before Sprint 135
    fixed it there: a user belonging to more than one customer silently
    sees only `me.customer_ids[0]`'s data, with no way to reach the
    others. Found during Sprint 135 while fixing the documents case,
    deliberately left alone in both of these (out of scope for that
    sprint). Same fix shape once prioritized: a picker when
    `customer_ids.length > 1` (names via `listAllCustomers`, server-
    scoped to the actor's own memberships), unchanged for the
    single-customer case.
15. **The Building picker (`listAllBuildings`, `frontend/src/api/
    admin.ts`) could outgrow exhaustive client-side paging.** Company is
    bounded by how many tenants exist on the platform; Customer is
    bounded by one provider's own client roster — both comfortably small.
    Building is different: a large facilities-management provider's
    serviced-property portfolio could plausibly reach into the thousands,
    at which point the picker's own exhaustive fetch (Sprint 135) means
    dozens of sequential API round-trips before the dropdown even
    renders — technically correct (no truncation) but a real, worsening
    UX cost as the row count grows, a growth shape Company/Customer don't
    share. Real fix, if/when this becomes a problem: a `?search=`
    server-side type-ahead endpoint instead of fetch-everything-then-
    filter-client-side. Not built — recorded so the shape of the eventual
    fix is on file rather than re-derived under pressure.
16. **Customer prices ARCHIVE — they do not hard-delete. This is
    deliberate; do not re-file it as a bug.** DELETE on both
    `/api/customers/<id>/pricing/` and
    `/api/customers/<id>/custom-pricing/` sets `is_active=False` and
    returns 204. It looked like a bug (Sprint 137 item 2: archived rows
    were still listed, so a "deleted" price reappeared greyed-out on the
    next load) and was fixed by HIDING archived rows by default rather
    than by switching to a real delete. The reason is a live FK:
    `ExtraWorkRequestItem.snapshot_customer_service_price` points at
    `CustomerServicePrice` on `SET_NULL`, so hard-deleting a contract
    row would irreversibly null the "which contract row produced this
    line?" link on already-shipped Extra Work. The money itself is safe
    either way — the `snapshot_*` columns, `ProposalLine` and
    `InvoiceLine` all carry their own amounts — but there is no reason
    to destroy the link when hiding solves the reported complaint.
    `CustomerCustomPrice` had no inbound FK when that decision was made
    and could have been hard-deleted by the letter of the rule, but both
    kinds share ONE table on the pricing page so "delete" has to mean the
    same thing on both — and Sprint 137 item 6 has since given it an
    inbound FK of its own (`snapshot_customer_custom_price`), so the
    original argument now applies to it directly too. Sprint 137 item 7's
    bulk action is therefore worded **"Archive selected"**, not
    "Delete selected", and puts the "Show archived" toggle on the same
    screen. Revisit only as a deliberate decision with the owner, and
    only alongside a plan for those two FKs.
17. **The bulk list actions are N sequential client requests — no bulk
    endpoint exists.** Sprint 137 item 7's Edit/Done mode on the customer
    pricing list, the Services catalog list and the Units catalog list
    issues one DELETE per selected row from the browser, sequentially,
    and reports per-row failures. That is honest and fine at the sizes
    these lists realistically reach (one category's prices; a provider's
    catalog), but a selection in the high tens would mean that many
    round-trips with no server-side transaction — a partial run is a real
    outcome, which is exactly why the UI names the rows that failed. If a
    tenant starts routinely selecting ~50+, the fix is a real bulk
    endpoint per list (`POST .../bulk-archive/` with an id list, one
    transaction, a per-id result array — the shape
    `CustomerServicePriceBulkRaiseView` already uses). Not built.
18. **`ExtraWorkRequest.category` and `ServiceCategory` are two
    unrelated "category" concepts, and both are still live.**
    `ExtraWorkRequest.category` is the fixed `ExtraWorkCategory` enum
    (DEEP_CLEANING, WINDOW_CLEANING, …) classifying ONE request;
    `ServiceCategory` is the catalog grouping that owns `Service` rows
    and drives per-customer pricing. Sprint 137 item 5 confirmed against
    the code that nothing reads the enum except the Extra Work
    serializers themselves (`create`/`list`/`detail`, plus the
    `category=OTHER ⇒ category_other_text` validation), `conversion.py`
    (which pins converted tickets to `OTHER`) and the demo seeder — in
    particular **`reports/` never reads it**, so the "reports may read
    it" worry in the original brief does not hold today. Item 5
    therefore left the field alone and populated, added the catalog
    filter as a separate axis on the cart, and labelled the request-level
    dropdown so the two stop being confusable. Migrating the enum away
    (or onto `ServiceCategory`) is a real decision with a data migration
    behind it and was bigger than that sprint; it stays open here.

19. **The Extra Work filter bar is TWO rows at 1280px, not one — and one
    is geometrically impossible without hiding filters.** Sprint 138 §6
    asked for a single wrapping line. Measured against the real built
    page with Playwright: the bar went from **3 ragged rows to 2 flush
    rows** at 1280px with **0px horizontal overflow** (also 2 rows at
    1440px, 3 at 1024px, 0px overflow at every width). One literal line
    cannot be reached: the content column is 966px wide at a 1280px
    viewport, and the nine controls need ~1356px at a usable 140px each
    plus 12px gaps. The only way to one line is a "more filters"
    disclosure — deliberately NOT built, because a collapsed group can
    hide an ACTIVE filter, which is exactly the "the interface does not
    explain itself" defect this sprint set out to remove. If the owner
    wants it, the safe shape is: collapse only the four cascade filters,
    auto-expand whenever any of them is set, and show a count badge when
    collapsed.
20. **Bulk (de)activate, bulk move and bulk archive are all N sequential
    client requests.** Sprint 138 added bulk move-to-category and bulk
    activate/deactivate on the Services list; both issue one PATCH per
    selected row from the browser, like Sprint 137's bulk archive/delete
    before them. Fine at catalog sizes, with per-row failure reporting
    so a partial run is never reported as clean. If a tenant starts
    selecting ~50+ routinely, the fix is one real bulk endpoint per
    action (id list in, per-id result array out, one transaction — the
    shape `ServiceBulkRaiseView` already uses). Not built.
21. **A GLOBAL category's cascade-archive reaches every provider
    company's services.** `ServiceCategory` has no `company` FK, so one
    category can hold services from several providers; Sprint 138 §2a's
    archive deactivates all of them. This is contained for now because
    category writes are SUPER_ADMIN-only
    (`_enforce_category_super_admin_only`) and the response reports
    `affected_company_count`, which the UI surfaces as an explicit
    warning when it exceeds 1. It is still a real cross-tenant blast
    radius sitting behind one button. The proper fix is the long-deferred
    "provider-scoped categories" decision recorded in the
    documented-intentional section (I-7) — until then, do not widen
    category writes beyond SUPER_ADMIN.

---

## SHIPPED

Append-only, one line per merged PR, newest first. #100–#114 are the
original record — wording preserved as shipped; #115 onward extends it
(Sprint 122.1). The old heading here cited `git log --oneline master` —
stale, since PR #116 renamed the default branch to `main`.

- **#126** (`751bb8d`) — Sprints 133, 134, 135 and 136 on one branch, one
  PR · **Sprint 133**: `build_extra_work_by_department_pdf` mixed two VAT
  bases in one table — detail rows rendered ex-VAT under an "Excl. BTW"
  header while every work-type/department/building total rendered
  inc-VAT, so a group's rows never summed to the figure printed beneath
  them. The document is now ex-VAT throughout (the headline keeps ex-VAT
  and gains VAT + inc-VAT alongside); the JSON/CSV payload was untouched.
  **Sprint 134**: six backend items — a double-reversal guard on
  `reverse_invoice` (service check + additive partial
  `uniq_live_reversal_per_original` constraint), `ALLOWED_HOSTS` admits
  the compose DNS name `backend`, `GET /documents/files/` paginated
  (manual wiring — it is a plain `APIView`), an additive
  `Invoice.granularity` field so an UNTAGGED
  `PER_BUILDING_DEPARTMENT_WORK_TYPE` invoice resyncs its grouping labels,
  `UnboundedPagination` on the Company/Customer/Building viewsets, and
  off-site encrypted backup machinery **built but never run**. Plus axios
  timeouts on both clients (`api` 30s, `refreshApi` 8s), fixing a hung
  refresh that left `refreshPromise` unsettled forever and a dead page
  the session-expiry handler never reached. **Sprint 135**: REVERTED
  134's item 5 — `UnboundedPagination` applied to every caller and killed
  the admin list pages' own prev/next, a worse failure than the picker
  truncation it fixed; the pickers were fixed client-side instead
  (`listAllCompanies`/`listAllCustomers`/`listAllBuildings`, 27 call
  sites). Also a SUPER_ADMIN company selector on ServicesAdminPage
  (Services + Units tabs; Categories are global and never affected), and
  a customer picker on `/my/documents` which had silently used
  `customer_ids[0]`. **Sprint 136**: one missed picker call site
  (`BuildingManagerCustomersPage`, capped at 100 not 200), a full `##
  NEXT` truth-up with every claim re-verified, and three CLAUDE.md
  lessons (array-literal render order defeats exhaustiveness checking;
  `pagination_class` is a contract with every caller; the `ConfirmDialog`
  imperative-dialog gotcha). Tail commits dropped a stale
  `test_double_reversal_still_unlocks` (Sprint 134's guard made its own
  setup raise) and pinned `tblib` so Django's `--parallel` runner can
  pickle tracebacks instead of masking failures.
- **#125** (`4c5798a`) — Sprints 130, 131 (+ its cross-tenant leak fix) and
  132 on one branch, one PR · **Sprint 130**: replaced the customer
  Permissions page's 17 per-key ✓/✗ columns with one summary chip per
  permission group (`PermissionGroupChip.tsx`), removed the sticky
  frozen-pane CSS the 17-column grid needed, measured zero horizontal
  scroll at 1280px in both locales. **Sprint 131**: `compute_extra_work_
  by_department` (Building → Department → Work Type), reusing the
  by-building report's row resolution verbatim; a Dutch-only branded PDF
  + CSV + customer Reports-tab tree; an untagged bucket instead of
  dropping pre-Sprint-127 rows, proven by a sum-to-flat-total invariant
  test. A cross-tenant name leak in the `?department=`/`?work_type=`
  scope echo was found in review and fixed same branch (`_scoped_label_
  name`, H-1/H-2). **Sprint 132**: `Customer.InvoiceGranularity.
  PER_BUILDING_DEPARTMENT_WORK_TYPE`, one level finer than PER_BUILDING —
  invoices grouped by Building + Department + Work Type, nullable PROTECT
  `department`/`work_type` FKs on `Invoice`; closed a staleness gap where
  relabelling an Extra Work during the DRAFT window could leave the
  invoice's own grouping stale once issued (`_resync_invoice_group_
  labels`, called before the status flips to ISSUED).
- **#124** (`765e94f`) — Sprint 129, session-expiry P1 + an owner-reported UI
  defect cluster · **P1**: a mid-session token-refresh failure used to wipe
  tokens and dispatch a dead `auth:logout` `window` event nothing listened
  for, leaving React still rendering the authenticated `me` while every
  subsequent request silently 401'd (a frozen page, recoverable only by a
  full reload). Fixed at the auth seam: the dead event is gone;
  `api/client.ts` calls a registered `onSessionExpired` handler exactly when
  a 401 cannot be recovered by a refresh; `AuthContext` clears `me` + the
  auth header and flags `sessionExpired`, so the existing route/role guards
  send the user to `/login` with a notice. A successful refresh still
  transparently retries (no logout); already-on-`/login` cannot loop. Also
  in this branch: the Customer Labels `ConfirmDialog` never called `.open()`
  (Delete did nothing) — fixed with the standard `useRef` + `.open()`
  pattern; the EW-detail relabel card now shows a success toast; the
  "CONCEPT (issued, unsent)" English-in-Dutch string (meaning the opposite
  of "concept") is gone from the wire — `labels_locked_invoice` returns the
  invoice number or `null`, nl+en lockstep; and a policy-toggle-grid
  cosmetic (the lone 5th "manage documents" toggle now spans full width via
  `:last-child:nth-child(odd)`). FE gate green (tsc, ESLint **48**, build);
  backend 127.1/127.2 suites green (29 tests). No automated test for the P1
  — no frontend unit-test runner exists yet — verified by review + the
  gates; the owed regression test is tracked in `## NEXT` (Frontend Testing
  Sprint).
- **#123** (`36641fd`) — Sprints 127 / 127.1 / 127.2 / 128, Department +
  Work Type end to end · two per-customer Extra Work label lists
  (`customers.Department` + `customers.WorkType` — one abstract base, two
  tables so a Department id can never fill the work_type slot; case-
  insensitive `Lower(Trim(name))` + `customer` uniqueness; CASCADE customer
  FK). Two nullable `PROTECT` FKs on `ExtraWorkRequest`; the one invariant (a
  label belongs to the EW's own customer) lives in one shared validator
  (`extra_work/label_validation.py`). Customer-scoped CRUD
  `/api/customers/<id>/{departments,work-types}/` (provider write; customer +
  BM read); delete-in-use refused with a coded 400 pointing at
  `is_active=False`. **127.1** — the provider relabel action
  `PATCH /api/extra-work/<id>/labels/` (`PROVIDER_ROLES`; ticket-converted EWs
  finally labellable) + the two FKs added to the EW audit trail. **127.2** —
  labels LOCK once the work is on an ISSUED invoice (an `InvoiceLine` whose
  invoice is ISSUED/SENT, not soft-deleted, not reversed — NOT `is_invoiced`);
  correction is credit → relabel → re-invoice, keeping the Department report
  and issued invoices reconcilable. **128** — the UI: a per-customer labels
  management page (two CRUD sections, provider write / BM read), two optional
  create-form pickers, an EW-detail relabel card (read-only-with-reason when
  locked), and a Customer → Building → Department → Work Type list-filter
  cascade; nl+en lockstep; ESLint held at **48**. Migrations `customers/0015`
  + `extra_work/0021`.
- **#122** (`9ae51c4`) — Sprint 126, customer Documents **UI** (frontend +
  rider backend) · a shared `DocumentsExplorer` (folder tree + bounded file
  pane + breadcrumbs + upload-with-progress + inline PDF/image preview +
  rename/move/delete + native drag-move) used by BOTH a provider sub-tab
  (`/admin/customers/:id/documents`, SA/CA) and a customer page
  (`/my/documents`, gated on `customer.documents.manage`); the two-sided
  ownership split (customers act only on their `origin=CUSTOMER` rows,
  provider rows read-only) lives in one `documentsAccess.ts`; reuses
  `DocumentThumb` / `BoundedList` / `PdfPreviewDialog`; backend `code`s
  surfaced as localized Dutch. **Rider backend** (the FE needed it): removed
  the now-dead `can_place_in_folder` guards (§2); a
  `GET /documents/files/?folder=<id>` list endpoint (the pane's data source —
  Sprint 125 shipped none) that 400s (not 500s) on a non-integer `?folder=`;
  the upload validator's stable `code` now in the JSON body for localization;
  a new additive policy field
  `CustomerCompanyPolicy.customer_users_can_manage_documents` (default True;
  migration `customers/0014`) wiring the module into the company-wide policy
  layer like Meldingen / Extra werk; `can_manage_documents` on `/auth/me/`
  for the customer sidebar gate. `customer.documents.manage` mirrored into the
  frontend `CUSTOMER_PERMISSION_KEYS`. ESLint baseline held at **48**.
- **#121** (`0aa38f6`) — Sprint 125, customer Documents **backend** · a new
  `documents` app under `/api/customers/<id>/documents/`: `DocumentFolder`
  (case-insensitive name uniqueness per (customer, parent) via two partial
  `Lower()` constraints; depth cap 10) + `Document` (opaque `public_id` UUID
  in URLs, never the row pk; denormalized `customer` mirrors
  `folder.customer`). Immutable `origin` (PROVIDER|CUSTOMER) stamped from the
  actor's role decides customer-side write eligibility. Provider gate =
  SA + CA-in-company only (BM/STAFF → 404 read, 403 write); customer gate =
  one coarse key `customer.documents.manage` via `user_can`. Four system
  folders (Facturen/Contracten/Overeenkomsten/Overig) auto-created per
  customer (Customer `post_save` signal + idempotent backfill). Upload
  validation (25 MB, `documents/uploads.py`): extension + declared MIME +
  magic bytes, real-OOXML-package check, UTF-8/no-NUL text check, no ZIP. A
  customer MAY place into system folders (files a contract into Contracten)
  but never rename/move/delete them. Audit: `DocumentFolder` in the generic
  trio; `Document` hand-crafted + filenames-only (a DELETE row answers "who
  deleted the contract"). nginx `client_max_body_size` 12M → 30M (docker
  frontend + host front-door). Migrations `documents/0001`–`0002`. **Backend
  only — the file-explorer UI is Sprint 126 (see `## NOW`).**
- **#120** (`ae8fa0e`) — Sprint-checklist close-out for PR #119 (docs-only) ·
  appended the #119 SHIPPED entry, rewrote NOW for the merged branch, added
  two maintenance rules (a PR cannot cite its own number → its SHIPPED line
  is appended by the NEXT branch; `## NEXT` cross-references cite by NAME,
  never number), and converted the stale `## NEXT`-by-number pointers in the
  frozen appendix to names. No code; appended here by Sprint 125 per the new
  rule (a PR cannot cite its own number).
- **#119** (`01e6eb5`) — Sprints 122 / 122.1 / 123 / 124 · **122** sharper PDF
  thumbnails (measure the parent tile + devicePixelRatio instead of the
  always-0 hidden canvas width), the credit-note flow completed (an unsent
  ISSUED reversal now reads as an amber "credit note — not sent" with a
  send-nudge banner, `credited_by_number` on both the provider and customer
  invoice serializers so a credited original stops reading as open debt, and
  the Unissue button hidden on a reversal the backend already rejects), and a
  SUPER_ADMIN per-company **email** notification opt-in separate from the
  existing in-app subscription (`notifications/0014`, default off);
  **122.1** this file restructured into NOW / NEXT / SHIPPED, the CLAUDE.md §8
  anti-drift rule added, the June build logs moved to
  `docs/archive/2026-06-sprints/`; **123** managed units per provider company
  (`extra_work.ManagedUnit`, migrations `extra_work/0018–0020` including the
  `custom_unit_label` free-text backfill, `/api/services/units/` CRUD, a Units
  tab on the Services admin page + the shared `ManagedUnitPicker`;
  `ProposalLine` deliberately excluded); **124** per-building Extra Work
  revenue split on the customer Reports tab
  (`compute_extra_work_revenue_by_building` sharing
  `_resolve_extra_work_revenue_rows` with the flat report,
  `/api/reports/extra-work-revenue-by-building/` + CSV/PDF,
  `ExtraWorkRevenueByBuildingChart` wrapped in `BoundedList`; no migration).
- **#118** (`daaaae3`) — Sprint 121 · a Sprint-117 padding regression on `.bounded-list` fixed (text no longer flush against the box); the nginx `.mjs` MIME-type root cause of broken PDF-thumbnail rendering in prod fixed (`.mjs` served as `application/javascript`, not `octet-stream`); PDF first-page thumbnails added for staff credentials via a new shared `<DocumentThumb>` (extracted from `AttachmentThumb`).
- **#117** (`79d814d`) — Sprint 120 · guarded `unbilled_extra_work_through` against an unresolvable billing month (K-1, `TypeError` → 500 risk on `/due/`), and fixed exhaustive-paging truncation (K-2) across `ExtraWorkListPage`, `FacturenPage`, and two further instances found while fixing it (`DashboardPage`'s billing KPI, `CustomerReportsPage`'s customer-facing report tab) — all four now page exhaustively instead of silently capping at 100/200 rows.
- **#116** (`70af26e`) — chore: renamed the default branch `master` → `main` (CI triggers + docs updated to match; no functional change).
- **#115** (`e355f61`) — Sprints 115–119 batch · docs restructure; **Sprint 116** CCA policy binding (`CustomerCompanyPolicy` now binds a company-wide CCA — see `sot-addendum-a-meeting2.md` §A.1.1); **Sprint 117** the shared `BoundedList` primitive + the CLAUDE.md "every server list must be bounded" rule; **Sprint 118** the intermittent frozen-screen bug root-caused and fixed (a native `<dialog>` left the document inert if unmounted without `close()` — shared unmount-cleanup across all 28 `ConfirmDialog` consumers + the attachment-preview dialog); **Sprint 119** the staff-credential PDF-preview modal + six known-issues fixes (the `/due/` current-month anchor, two stale invoicing docstrings, a `company_ids_for` scoping de-dupe, a dead `LoginPage` toggle, a stale comment, three `ConfirmDialog` close-on-error fixes).
- **#114** (c5ac3d4) — Invoice UI polish.
- **#113** (ae1d855) — Post-clickthrough fixes · **numbering moved from ISSUE to SEND** (so an ISSUED-but-unsent invoice shows CONCEPT and un-issue strands no number) + the `ISSUED → DRAFT` un-issue action + the arbitrary billing day `Customer.invoice_day_of_month` (nullable 1–28, takes precedence over `invoice_day_rule`; migration `customers/0013`).
- **#112** (ef5677e) — **Invoicing subsystem** (Phases 1–5, the whole `invoicing` app) + two small fixes alongside · DRAFT→ISSUED→SENT lifecycle, gapless per-company-per-year numbering, reversal/credit-note, two-page Dutch PDF, provider Facturen UI + customer-portal visibility. Migrations `invoicing/0001–0003`, `customers/0012`. See [`sot-addendum-b-invoicing.md`](../product/sot-addendum-b-invoicing.md).
- **#111** (e73bd4a) — Sprint 111 · "My Work" made role-adaptive: STAFF keeps the slot agenda; BUILDING_MANAGER gets an assigned-tickets view via a new opt-in `?my_managed` ticket filter; hidden for SUPER_ADMIN + COMPANY_ADMIN. Added `docs/product/role-visibility-matrix.md`.
- **#110** (cd86e3a) — Round-4 polish · Responsible-managers + Scheduling cards default-collapsed, taller Extra Work live-preview (embed fills the pane, measured 420→747px), seed 15 extra Osius demo buildings so the pickers overflow the capped scroll.
- **#109** — Audit fixes + round-3 + SA notifications · P2-1 EW billing audit, P2-2 ticket customer-approval `user_can` gate, P3-1 billing localtime, P3-3 SA CONVERTED terminal guard; composer preview-to-bottom + labeled buttons, multi-select scroll proof + unbounded-list sweep, dashboard density band, customer-scoped report charts (revenue/over-time/status), per-ticket collapse; SA per-company notification subscriptions (in-app) + view-as feed; docs polish.
- **#108** — Owner-batch-2 · Option-A dashboard rebuild, single-row proposal composer + `custom_unit_label` on ProposalLine, Bulk adjust (raise+lower), toggle/checkbox + multi-select sweep, customer Invoices+Reports sub-tabs, EW-list mark-invoiced→Facturen pointer, collapsed ticket-detail cards, seed enrichment.
- **#107** — Detail/dashboard polish · RF-17 collapsible/wider ticket-detail right column, RF-18 dashboard info widgets, RF-19 stable proposal add-line grid.
- **#106** — Combined queue · RF-8 permission module bundles, RF-9 calm assignment area, RF-13 Facturen invoices v1 (customer+building filters), RF-16 dashboard = attention cards (full lists on Tickets/Extra Work only).
- **#105** — EW comfort + branded PDFs · RF-14 collapsible/scrollable EW-detail cards + preview toggle, RF-15 Osius-logo header + embedded DejaVu font with real € on both PDF families.
- **#104** — IA & Effectiveness · disjoint Notificaties/Berichten (message events out of the feed by default), customer-detail content tabs 4→2 with filter chips, inbox unread-toggle + mark-all-read.
- **#103** — RF-1 message inbox · WhatsApp-style aggregated inbox over ticket + Extra Work threads, per-recipient read cursors, logo/photo avatars, RF-11 EW Messages card restyle.
- **#102** — Small independents · `sub_tasks` CUSTOMER_USER redaction (privacy) + RF-2 unified Add-price flow with Other/Custom (`custom_unit_label` on CustomerCustomPrice).
- **#101** — PDF & Preview sprint · proposal-PDF quality (Dutch), split-screen live proposal preview, attachment thumbnails.
- **#100** — Quick-wins RF-3/4/5 · top-level Tickets page, tucked ticket audit-timeline, attachment type + in-app preview.

---

# Appendix (frozen — historical reference, not day-to-day reading)

Everything below is kept in this file (rather than moved to
`docs/archive/`) because it is still occasionally referenced by ongoing
work — the RF numbers and backlog numbers get cited by number elsewhere in
this file and in commit messages. It is otherwise not maintained; treat
dates and "current" framing inside it as of the date shown, not as
current truth.

## Sprint 9 — Feedback & Backlog Notes (captured 2026-06-23)
Göktuğ's pre-feedback recollections, reconciled with Ramazan + father
feedback over the following weeks. Several intersect shipped work —
flagged inline at the time.

1. **Custom units on the Service "Other" unit type.** "Other" should accept free-text units (cm, m³, …). Possibly customer-specific — even per-room. Open: how far down unit definitions go (customer / building / room). **Resolved 2026-07-27: Sprint 123 decided the scope is per PROVIDER COMPANY — see `## NEXT`.**
2. **Dedicated invoices page + workflow.** Extra work lives in the stream today; may want its own invoice page/workflow; possible "invoiced" status on EW. **Shipped — the invoicing subsystem (`## SHIPPED` #112).**
3. **Invoice PDF + send-to-customer.** A PDF invoice system; likely Ramazan feedback on how invoices / customer feedback get sent. **Shipped — the invoicing subsystem (`## SHIPPED` #112); the send-nudge + credited-original marking shipped in Sprint 122.**
4. **Notifications history / read messages.** Can't reliably see past notifications; need full history incl. already-read items. **Shipped — RF-1 (`## SHIPPED` #103).**
5. **Attachment in-app preview.** Clicking an attachment downloads it; want in-app viewing, with PDF preview inside the app. **Shipped — RF-5 (`## SHIPPED` #100) + RF-12 thumbnails (#101) + Sprint 121/122 sharpness fixes.**
6. **Customer "event" + "department" fields.** On customer create, possibly two more dropdowns: event + department. Department likely customer-specific. "Event" may be a selectable event type, not a category — undecided. **Resolved 2026-07-27: the two fields are per-customer label lists on Extra Work — "Department" (a sub-client / segment; "Event" is one VALUE in it, never its own field) and "Work Type". Tagging is in flight now (Sprint 127 backend / 128 frontend); the grouped report + invoice grouping are the queued follow-up (Sprint C). See `## NEXT`, "Department + Work Type."**
7. **Right-side card layout / density.** Assignment / responsible-manager / building-manager / scheduling / ticket-detail / add-slot / add-subcard / manager sections are good UX. Possible: make the right-side cards larger with more horizontal space. **Shipped — RF-9 + RF-17 (`## SHIPPED` #106, #107).**
8. **Customer surfaces — keep combined.** Separate pages for a customer's EW / quote-requests / tickets likely won't be liked; want one customer page with tabs/subsections. **Shipped — M6 (customer drill-in sub-tabs), predates this backlog.**
9. **Baseline:** system in good shape at the time; editing customers/users + general flows fine; no major issues.

### Received feedback (logged as it arrived through the #100–#110 queue)

**IA decisions (2026-06-25):** Notifications + Messages both stay, disjoint — message-type events default OFF in the feed (user-mutable opt-in); names locked Notificaties / Berichten / Melding-reserved; customer detail content tabs merged 4→2 with filter chips; inbox gets unread toggle + mark-all-read; Request-a-Quote nav stays (Ramazan); SA notification-emptiness confirmed BY DESIGN (deliberate fan-out exclusion, directed messages bypass it) — documented, not changed (later made opt-in per company, `## SHIPPED` #109, then given a separate email opt-in in Sprint 122).

**RF-1 — Notifications "messages" overview, WhatsApp-style (father, received 2026-06-23, voice memo).** He wants the main messages view to work like a WhatsApp chat list: each row a ticket, an avatar (last actor or customer logo), an unread-count badge, searchable/filterable. **Design locked 2026-06-24:** per-user-per-thread read cursors (`MessageReadCursor`); read receipts ("who hasn't read") are provider-management-only (SA/CA/BM); covers both ticket + Extra Work threads with kind/date-range/search/unread-only filters, computed per-viewer through the existing five-mode visibility matrix. Additive `User.profile_photo`, `Customer.logo`, `Company.logo`. **RF-11** (restyle the EW detail Messages card) rode along. **Shipped — `## SHIPPED` #103.**

**RF-2 — Fold custom price lines into the regular "Add price" flow (Göktuğ, 2026-06-23).** Merge the separate "add custom price" surface into the regular Add price line flow: an "Other"/"Custom" dropdown option + free-text service name + free-text unit name. **Shipped — `## SHIPPED` #102.**

**RF-3 — Tickets as a top-level page (Ramazan, 2026-06-23, in-person).** Mirror Extra Work: a top-level Tickets page with New Ticket reached from inside it. **Shipped — `## SHIPPED` #100.**

**RF-4 — Ticket detail: the audit timeline dominates the page (Ramazan, 2026-06-23; raised twice).** Move it to a discreet spot — a right-corner control, a tab, or a collapsed drawer. His principle: at a glance minimal, depth behind a click. **Shipped — `## SHIPPED` #100.**

**RF-5 — Attachment preview (Ramazan, 2026-06-23; confirms backlog #5).** Show file type without clicking; clicking opens an in-app view instead of downloading. **Shipped — `## SHIPPED` #100 (base), #101 (thumbnails), Sprint 121/122 (sharpness).**

**RF-6 — Live proposal-PDF preview, split screen (Ramazan, 2026-06-23).** While building a price proposal, the right half shows the proposal rendered as it will look, updating as lines are entered. **Shipped — `## SHIPPED` #101.**

**RF-7 — Extra Work detail: pricing section "big tabs" (Ramazan, 2026-06-23; location confirmed, element TBC).** Big tab/block elements where he prefers click-in navigation. Göktuğ confirms it's the EW pricing section; the exact element is still to be pinpointed. **Still open — pinned inside `## NEXT`, "Fixing & Auditing Sprint."**

**RF-8 — Simplified module/permission surface + future modules (Ramazan, 2026-06-23).** Think of melding/extra work as modules; one user-management surface grants module access; keep the visible permission UI to 3–4 coarse toggles per module, with fine-grained permissions bundled behind them. **Shipped — `## SHIPPED` #106 (module cards Meldingen + Extra werk, master on/off + 3 coarse toggles, full depth behind "Geavanceerd").**

**RF-9 — Assignment/slot page density (Ramazan, 2026-06-23; confirms backlog #7).** Too much info at once; enlarge/clarify the sub-task/detail areas, or a simple "assign to someone" flow. **Direction locked 2026-06-26:** simple-first AND enlarged details, combined. **Shipped — `## SHIPPED` #106.**

**RF-10 — Proposal PDF: text overlap + professional pass, Dutch-only (Göktuğ + Ramazan, 2026-06-24).** Root cause: `proposal_pdf.py` wrote `"{qty} x {UNIT_ENUM}"` into a fixed-width cell with no fitting; long enums overflowed. **Shipped — `## SHIPPED` #101** (humanized Dutch unit labels + width-aware cells + Dutch number/money formatting).

**RF-11 — EW detail: Messages card looks out of place (Göktuğ, 2026-06-24).** Rode along with RF-1. **Shipped — `## SHIPPED` #103.**

**RF-12 — Attachment thumbnails without a click (Göktuğ, 2026-06-24).** Images render the actual image; PDFs render a first-page thumbnail. **Shipped — `## SHIPPED` #101** (sharpness fixed later in Sprint 121/122).

**RF-13 — Invoices get their own page (Göktuğ, 2026-06-24).** Confirms backlog #2. **v1 scope locked 2026-06-26:** overview page, customer+building filters, existing mark-invoiced granularity, tickets get NO invoiced status. **Shipped — `## SHIPPED` #106** (v1), then the full invoicing subsystem (#112).

**RF-14 — EW detail pricing area: preview squeeze + long-list comfort (Göktuğ, 2026-06-25).** The live proposal preview (RF-6) squeezes the Pricing proposal section; make Requested services + Pricing proposal collapsible/scrollable. **Shipped — `## SHIPPED` #105.**

**RF-15 — Formal branded PDFs (Göktuğ, 2026-06-25).** Osius logo header + embedded font with real € across proposal PDFs and report PDF exports. **Shipped — `## SHIPPED` #105.**

**RF-16 — Dashboard and Tickets show nearly the same content (Göktuğ, 2026-06-25).** **Direction locked 2026-06-26:** dashboard = overview/attention cards ("Te bevestigen", "Niet toegewezen", "Recente activiteit"); full lists live exclusively on Tickets / Extra Work. **Shipped — `## SHIPPED` #106.**

**RF-17 — Ticket-detail right-side sections not collapsible, narrow column (Göktuğ, 2026-06-27).** Make them collapsible and widen the column. **Shipped — `## SHIPPED` #107.**

**RF-18 — Dashboard too empty (Göktuğ, 2026-06-27).** Add compact info widgets: unread messages, awaiting pricing, proposals awaiting customer, month billing open/invoiced, today's slots. **Shipped — `## SHIPPED` #107.**

**RF-19 — Proposal-builder add-line form reflows (Göktuğ, 2026-06-27).** Stabilize the grid so it doesn't push the note field down as content grows. **Shipped — `## SHIPPED` #107.**

**Owner review round 2 (2026-06-28), all locked:** dashboard rebuilt to Option A (4-KPI hero · 'Aandacht nodig' priority list · 'Vandaag' column · 'Mijn werk' chips); proposal composer single-row with modal editors; proposal lines gain a Custom unit (`custom_unit_label` on ProposalLine); bulk-raise becomes Bulk adjust (raise+lower, guarded); platform rule: toggles for boolean state, checkboxes (restyled) for selection; system-wide multi-select sweep (scroll + Select all/Clear all); customer detail gains Invoices (view-only + Facturen link) and Reports sub-tabs; seed data enriched; EW-list mark-invoiced action moves to Facturen; ticket-detail right cards default-collapsed with Workflow open; zero-price proposal send stays permitted; demo data cleanup declined; E2E deferred until after Ramazan+father feedback. **Shipped — `## SHIPPED` #108.**

**Owner review round 3 (2026-07-20):** five feedback items on the deployed #108 — proposal composer PDF-preview-to-bottom + labeled Add-line/Cancel buttons; prove the multi-select scroll cap bites + sweep for other unbounded lists; dashboard open-vs-invoiced hero split + Facturatie mini-table + Laatste-tickets list; customer Reports tab real per-customer GRAPHS; ticket-detail collapse per-ticket (reset on navigate). **Shipped — `## SHIPPED` #109.**

**Owner review round 4 (2026-07-20):** Responsible managers + Scheduling cards default-collapsed; Extra Work live-preview pane given a real height (measured embed 420px → 747px); building-list cap re-confirmed with 18 seeded demo buildings (measured overflow). **Shipped — `## SHIPPED` #110.**

**Owner review round 5 (2026-07-20):** "My Work" made role-adaptive and hidden for SA + CA. **Shipped — `## SHIPPED` #111.** Two open discussion items from this round are carried in `## NEXT`, "Fixing & Auditing Sprint" and "Mobile responsiveness."

**Meeting notes (2026-06-23):** Department/event are category-like fields; names must stay editable/customer-flexible — refines backlog #6. Ramazan will do a full side-by-side review vs their current system (this is the review `## NEXT`, "Light/advanced mode split," is gated on). He validated the pricing work (bulk raise, customer-specific prices, price history preserved). The credentials/permissions area of their current tool is their worst pain point.

## Documented-intentional behaviors (audit 2026-07-20)
These surfaced during the #109 audit and are intentional — recorded so a future audit does not re-flag them:
- **(I-1)** The ticket-level `/tickets/<id>/unable-to-complete/` endpoint is superseded by the slot-completion flow (AgendaPage → `send_slot_unable_to_complete_email`) and is intentionally left unsurfaced.
- **(I-2)** The legacy `ExtraWorkPricingLineItem` route is alive by design (older EWs keep it) and has no `actual_hours` column by design — it never gates the completion transition.
- **(I-3)** The SA notification feed is empty by design (the in-app fan-out deliberately excludes unsubscribed SUPER_ADMIN; only directed messages reach them) — opt-in per company (`## SHIPPED` #109), with a separate email opt-in added in Sprint 122.
- **(I-4)** `clear-invoiced` clears by the EW's CURRENT billing month (COALESCE(invoice_date, spawned-ticket completion)), not the month it was originally marked in.
- **(I-5)** The customer logo GET is open to any authenticated user by design; writes are gated (a customer's logo only by that customer's CUSTOMER_COMPANY_ADMIN; SA may change any).
- **(I-6)** The user profile-photo GET is open by design; writes are self/SA only.
- **(I-7)** `ServiceCategory` stays global (system-wide unique `name`, no
  `company` FK) while `Service`, `CustomerCustomPrice`, and `ManagedUnit`
  are all company-scoped — found during Sprint 123, decided intentional
  in Sprint 136: reconciling them means migrating a system-wide unique
  constraint with live data behind it (splitting one global category
  namespace into per-company ones, backfilling every existing row's
  company, and resolving any name collision that split would create) — a
  real schema migration, not a small change, and not worth it without a
  concrete need driving it. Recorded so a future sprint touching either
  catalog doesn't re-flag it as an oversight.

---

## Moved to `docs/archive/` in Sprint 122.1

Purely historical build logs that no live work still references by
number — moved out rather than kept here. Each carries the standard
`ARCHIVED` banner; each is also listed in `docs/README.md`'s Archive
section.

- [`archive/2026-06-sprints/meeting2-and-early-sprints.md`](../archive/2026-06-sprints/meeting2-and-early-sprints.md) — Sprint 0–9, the Ramazan-Meeting-2 near-term block (CP, M1–M7), and the 2026-06-23 phase-order roadmap.
- [`archive/2026-06-sprints/invoicing-build-log.md`](../archive/2026-06-sprints/invoicing-build-log.md) — the invoicing subsystem's Phase 1–5 build log (superseded by [`sot-addendum-b-invoicing.md`](../product/sot-addendum-b-invoicing.md)).
- [`archive/2026-06-sprints/sprint-116-119-build-log.md`](../archive/2026-06-sprints/sprint-116-119-build-log.md) — Sprint 116 (CCA policy binding), Sprint 118 (the frozen-screen bug, root-caused and fixed), and Sprint 119 (credential PDF modal + known-issues, with the K-1/K-2 findings corrected to reflect their actual Sprint-120 fix).
