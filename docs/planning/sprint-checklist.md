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
- ESLint baseline = **44** (42 errors, 2 warnings): add **no** new violations; **never** a synchronous setState in an effect body; for prop-derived state, **key the component by id** (no resync useEffect). (History: 49 → 48 when Sprint 115 removed an unused hook, `useEffectivePermissions.ts`, that carried one violation. This line then said 48 until Sprint 155, which was stale from Sprint 152 onwards — Sprints 152–154 each removed a violation without correcting it, and CLAUDE.md said 45 while this said 48. Sprint 154 §B deleted the effect that took it to **44**; Sprint 155 corrected both files to agree. When the count changes, change it in BOTH places in the same commit.)
- **PR cadence (corrected 2026-07-27 — the old "PR per sprint" line was stale):** several sprints now land on ONE shared branch and the owner opens ONE PR after the last of them (Sprints 115–119 → PR #115; Sprints 122–124 are following the same pattern on `feat/sprint-122`). CI (+ Codex review) still gates that one PR when it opens. Migrations stay additive + back-compat regardless of when the PR opens.
- Each prompt starts with a sync + a grep GUARD proving the right base, captures the ESLint baseline, applies any new migration to the dev DB before a FE smoke, and ends with an adversarial self-review. Screenshots/smokes via **token-inject** (the e2e login form is flaky).
- Co-author trailer on commits: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` (the old line here named a different model — verify the current one in `CLAUDE.md` before reusing this, it has changed before).

---

## NOW

**Branch:** `feat/sprint-155-owner-feedback-2` — Sprint 155, the owner's
second feedback round. **CC did NOT open a PR and did NOT deploy.**

**Cut from the tip of `feat/sprint-154-owner-feedback` (`a29adeb`), NOT
from `main`.** Neither #153 nor #154 was merged when this branch was cut,
so the three must merge IN ORDER: **#153 → #154 → #155**. #155 contains
all of #154, which contains all of #153.

### The owner-visible changes, in plain words

- "Extra Work" in the menu is a folder again, but the word itself is
  still a link — clicking it opens the list, and the small arrow beside
  it folds the four entries away. "Extra Work Request" is now one of
  those entries.
- The "New Extra Work" button asks which of the three things you mean —
  order the work now, ask for a price first, or set up work that
  repeats — and each choice says in one line what it is for.
- The Linked buildings card on a customer's page is no longer half
  empty: each building shows its city and postal code, how many
  customers and managers are at it, and a marker when it is inactive.
  The whole row is a link to the building.
- The Documents page now looks like the Pricing page: folders are big
  cards with the number of files on them, and a large "+" card at the
  end makes a new one.
- Nothing anywhere is directly editable any more. Every list has an Edit
  button; the tick boxes, the remove buttons and the Add button only
  appear after you press it. The Permissions page is the one exception,
  as asked.
- Hours: you now choose which employees you are entering a week for, and
  it is a separate choice from the filter on the table. Pick several and
  you get a block each. One line at the top fills the same number of
  hours into every day for every one of them, and one Save writes the
  lot.

### §1 — the Extra Work group, with a clickable parent

Sprint 154 flattened the M3 group because its parent was a button that
only expanded: reaching the list took two clicks. Putting the group back
as it was would put that back too. The label now navigates and a
separate chevron folds the children; the children default to OPEN, since
closed-by-default is what made the group a detour in the first place.

`end` on the parent is the active-state carve-out, extended rather than
replaced — an exact match, so a child route lights up the child and not
the parent. **Measured:** on `/extra-work/new` the parent is inactive and
the child is active.

Gates unchanged. One consequence worth stating: an actor with
`canAccessPlannedWork` but NOT `canAccessExtraWork` would lose Recurring
Work entirely if it were only ever a child, so it stays a top-level link
for them. The nesting is IA, not a gate.

§1b's chooser is a NON-native overlay (`ChoiceDialog`), conditionally
mounted, like `BulkAssignDialog`. `ConfirmDialog` stays native and
ref-driven everywhere it is used — that split is unchanged.

### §2 — the Linked buildings card, and an N+1 it uncovered

The row now carries the postal code, the active state and two counts,
all annotated by one shared helper called from BOTH anchors (the
customer's side and the building's side). An anchor that skipped the
annotation would reintroduce the N+1 on that side only, which is the
drift having one serializer is meant to prevent.

**The query guard earned its keep on its first run: 6 queries for 2
links, 14 for 10.** The cause was PRE-EXISTING — Sprint 154 §G.2 added
`customer_name` to this serializer for the building's card but only added
`select_related("customer")` to the building-side queryset, so the
customer-side one had been fetching the customer per row ever since.

**Measured, same customer, same 1440px viewport, two builds:** ink
reaches **160px of a 492px row (33%)** before, **502px of 512px (98%)**
after — the empty right-hand side goes from 332px to 10px. The row is an
`<a>` after and was a `<div>` before.

*The prompt's premise was wrong on one point:* it said Sprint 154 had
already made this row a link. It had not — 154 §G.1 added the
click-through on the customer's Buildings SUB-PAGE; this preview card was
still plain divs. Added here rather than kept.

### §3 — Documents in the pricing card language

Reuses `.pricing-category-*` with a `.doc-folder-card` modifier rather
than cloning the rules. **Measured:** 5 cards, every one 255x121px, the
"+" card last, root crumb present, zero raw i18n keys.

The explorer now opens at the ROOT level on a grid, the way the pricing
page opens on its category grid. Sprint 126 auto-selected the first root
folder; `null` is a first-class level now, and nothing is lost because
every file lives in a folder (`Document.folder` is non-null). An empty
level renders the grid directly rather than through `BoundedList`, which
swaps children for the empty state at count 0 and would remove the "+"
card at exactly the moment it is the only thing worth clicking.

**Two of §3's four bullets were already done** and are unchanged: file
rows have carried an icon, a readable size and a date since Sprint 126,
and Sprint 154 §L.1 already rewrote the empty state to say what to do.

### §4 — the system-wide rule, in one place

`lib/useEditMode.ts` is `CustomerPricingPage`'s pattern lifted out, not
copied. Both properties are DERIVED: `editMode` is
`requested && something to act on` (closing BOTH the open-on-empty case
and the empty-while-open one, which gating the button cannot), and the
selection is filtered to what is still selectable (the Sprint 138 §3
phantom-success bug). Neither needs an effect, which matters — a resync
effect would be a synchronous setState in an effect body.

Three admin lists keep a selection that spans PAGES, so they take only
the MODE from the hook and clear their own state through `onExit`.
Adopting the hook's selection there would silently drop the off-screen
half of a selection.

**Fixed:** BuildingRelationCard (x4), BuildingsAdminPage,
CustomersAdminPage, CustomerBuildingsPage, HourTypesTab.
**Checked and already correct:** CustomerPricingPage, ManagedUnitsTab,
ServicesAdminPage, CustomerUsersPage, CustomerContactsPage, the four
form pages, and CustomerPermissionsPage (the stated exception).

**The sweep's real find was the hour-types tab.** "Deactivate" fired
straight off the row click with no confirm and no mode, so one mis-click
took an hour type out of every picker in the module.

**Measured:** building relation cards 0 checkboxes / 0 Add / 0 remove
read-only, 4 edit toggles; after one toggle 2 / 1 / 1. Buildings list
0 → 23 checkboxes; Customers list 0 → 5. Hour types 0/0/0 buttons
read-only → 6/6/6 in edit mode.

### §5 — the week grid was wrong, and the owner said why

`HoursAdminPage` passed `filters.employee` straight into the grid, so one
single-select control answered both "whose rows am I looking at" and
"whose week am I writing". The grid now knows nothing about the filter:
it renders a block per employee it is GIVEN, and the caller owns the
selection. On `/admin/hours` that is a multi-select of its own; on
`/my-hours` it is one person, which is why one component serves both.

The wire change is additive: a cell may carry its own `employee`, and the
top-level one becomes the DEFAULT, so every Sprint 154 client keeps
working. Resolution still happens inside `TimeEntrySerializer` — whose
`employee` queryset is scoped — rather than in the input serializer,
because an unscoped `PrimaryKeyRelatedField` there is the existence
oracle H-1 forbids. The non-manager guard was extended to cover per-cell
ids; a guard that only read the top-level field would be bypassed by
putting the other person's id on the cells.

The edit map is keyed employee-FIRST: the same (hour type, building) row
exists under several people and their cells must never collide.

Reads are one per selected employee through `Promise.allSettled`, so a
failure for one person cannot discard anybody else's rows. The lock stays
a separate read defaulting to OPEN — Sprint 154 had them in one
`Promise.all` and a 400 on the lock threw away entries whose own request
had returned 200.

**NOT copied from the reference system:** contract hours, "valid from"
windows, a work type on the hour row. We have no such model, and
inventing one here would put a fiction in front of the real one.
Everything he actually described is present, adapted.

**Measured end-to-end on the built app:** two employees selected → 2
blocks, apply bar with all 6 controls, Mon–Sun + Total columns, Add row
per block, one Save. Apply-to-all at 7,5 Mon–Fri filled 10 of 14 cells
with one distinct value, row totals 37.50 each, grand total "75 u voor 2
medewerkers". A real save then wrote **10 changes**; read back from the
API: 5 rows each for employees 2 and 3, dates 2026-08-03..07, hours 6.25,
`weighted_hours` 6.25 (so the multiplier snapshot was written), ISO week
2026-W32 derived.

### §6 — the ESLint baseline said three different numbers

CLAUDE.md said 45, the checklist's Conventions said 48, a second
checklist line also said 48; the real count is **44**. All four now say
44, with a note to change both files in the same commit. Sprints 152-154
each removed a violation without correcting the line, which is how it
drifted in two files at once.

### Gates

Backend: `test timesheets customers buildings extra_work audit
documents` — `documents` added to the prompt's list because §3 changed
it. 27 new tests across
`timesheets/tests/test_sprint155_multi_employee_week.py` (13),
`customers/tests/test_sprint155_linked_buildings.py` (8) and
`documents/tests/test_sprint155_folder_file_count.py` (6).
`makemigrations --dry-run --check` → *No changes detected*. **No
migrations this sprint** — every backend change is a serializer field or
a queryset annotation.

Frontend: `tsc` clean, `eslint .` **44 problems (42 errors, 2
warnings)** — unchanged from the Sprint 154 baseline, zero added, no new
`eslint-disable` — and `npm run build` ✓.

i18n: all **11 namespace pairs** equal (`common` 2100/2100, `extra_work`
470/470, and nine more). Then the check that matters: **661 `t()` call
sites across the 18 changed files, resolved against the namespace each
component actually declares, 0 misses.** That audit found two real
misses on `ExtraWorkListPage` — `list.filter_category_group_live` and
`_historical` lived only in `common` while the page defaults to
`extra_work` — the same defect Sprint 154 §N.2 fixed a hundred lines
away, which the language-only comparison could never see.

**Measured, not inferred:** every layout and behaviour claim above came
from Playwright geometry off the built app served through a
Host-rewriting proxy. **0px of horizontal overflow at 1024 / 1280 /
1440** on all five pages touched, and zero raw i18n keys on any of them.

---

## NEXT

Single ordered queue — replaces the four lists this used to be spread
across ("Owner's forward queue", "Deferred / undecided items", "Standing
milestones", "Deferred"). All four are now retired; every genuinely-open
item from them lives here, and every already-shipped or already-decided
item has moved to `## SHIPPED` or been resolved below instead.

0. **The week grid reads one request per selected employee.** (Sprint
   155 §5, deliberate.) `HoursAdminPage` fires one `listTimeEntries` per
   person through `Promise.allSettled`, so a failure for one cannot
   discard anybody else's rows — but an operator who selects forty
   people makes forty requests. The count is bounded by their own
   choice, which is why this was acceptable to ship.
   Fix shape if taken up: an `employee__in=` filter on the entries list,
   then ONE request grouped client-side. Do **not** solve it by dropping
   the employee filter and fetching the whole company's week — that
   trades a bounded request count for an unbounded page size, and
   `page_size=200` would silently truncate a busy week.

0. **Three admin lists keep a selection that spans PAGES.** (Sprint 155
   §4, deliberate.) Buildings, Customers and the customer's Buildings
   sub-page union the current page's ids into what is already chosen,
   and the bulk action fires against the union — so they take only the
   MODE from `useEditMode` and keep their own selection array.
   Worth revisiting on its own merits: a destructive bulk action whose
   count includes rows scrolled off two pages ago is exactly the kind of
   thing §4's intent step exists to prevent, and the operator cannot
   verify it. Changing it is a behaviour change, not a refactor, so it
   was not folded into a sweep about something else.

0. **A COMPANY_ADMIN in MORE than one provider company cannot open
   "Mijn uren".** (Sprint 152.1 §2, deliberately deferred.) The page
   sends no `?company=`, so `views_common.resolve_view_company` refuses
   to guess and returns `timesheet_company_required`. Everyone else
   resolves cleanly: STAFF and BUILDING_MANAGER hold a one-company scope
   in practice, and SUPER_ADMIN no longer sees the page at all.
   Fix shape if taken up: a compact company selector on the page itself,
   sourced from the timesheets scope helper — **not** from
   `me.company_ids`. That field is `CompanyUserMembership` only, and a
   STAFF member belongs to a company through `BuildingStaffVisibility`,
   so it would report zero companies for exactly the role that uses the
   page most. Same trap as the employee-picker one §1a avoided: the
   membership question has three answers, not one.

0. **`ServiceDetailView` is not narrowed for a CUSTOMER_USER.** Sprint
   147 stopped a customer LISTING the provider's general catalog
   (`ServiceListCreateView` requires an active, currently-valid
   `CustomerServicePrice`), but `/api/services/<id>/` still resolves any
   service of their provider company. So a customer cannot enumerate the
   catalog, but can still fetch one by id — walking integer ids
   reconstructs it. Left deliberately: narrowing the detail view risks
   404ing a service referenced by an older request whose agreed price has
   since expired, and that path was not traced. Fix shape if taken up:
   apply the same predicate as the list view, but first confirm nothing
   customer-facing resolves a historical line through this endpoint
   (Extra Work detail uses the `snapshot_*` columns, which is why it is
   probably safe).

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
    a CI gate; do not regress the ESLint baseline (44 — see Conventions;
    this line said 48 until Sprint 155 corrected it). No frontend
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
    *(Sprint 153 built the FIRST one — `POST /api/customers/bulk-
    deactivate/` — so there is now a second reference implementation
    alongside the bulk-raise view, this one all-or-nothing rather than
    per-id-result. The three lists named above are still N sequential
    requests.)*
    *(Sprint 154 added four more — `buildings/bulk-link/`,
    `bulk-deactivate/`, `bulk-update/` and `customers/bulk-update/` —
    and settled the shape question: ALL-OR-NOTHING with one constant
    rejection body, never a per-id result array, because a per-id array
    over a top-level tenant list is an existence oracle. The pricing /
    Services / Units lists are STILL N sequential requests; their ids
    are already URL-scoped to one customer, so a per-id array is safe
    there and the shape question above still applies to them.)*
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
    *(Sprint 153 shipped `POST /api/customers/bulk-deactivate/`, which
    is the same idea for the CUSTOMERS list. It chose all-or-nothing
    over a per-id result array because a customer id the caller cannot
    resolve must not be reported distinguishably from one that does not
    exist — H-1. A per-id result array is fine for a list whose ids are
    already URL-scoped to one customer; it is an existence oracle for a
    top-level tenant list. Worth settling before the next bulk endpoint
    is written.)*
21. **Two PRE-EXISTING existence oracles of the same class as Sprint
    142.1 §1, found by auditing every `validate*` method that runs an
    ORM query.** Neither was introduced by this branch and neither was
    fixed here (the round was explicitly scoped to three one-liners), but
    both are the same shape and should be closed together.
    (a) `accounts/serializers_invitations.py:159-161` resolves
    client-supplied `company_ids` / `building_ids` / `customer_ids`
    BEFORE the actor-scope authorisation that follows it, so an unknown
    id returns `"Unknown company id."` while a known-but-foreign id
    returns the scope error — distinguishing "exists" from "exists but
    is not yours". Leaks bare id existence, not names.
    (b) `tickets/serializers.py:1131` (`TicketCreateSerializer`) and its
    twins at `extra_work/serializers.py:1245`/`:1632` check the
    `CustomerBuildingMembership` link for a client-supplied
    (customer, building) pair BEFORE any role branch, on plain unscoped
    FK fields — so any authenticated writer can probe whether an
    arbitrary pair is linked. The fix in both cases is the Sprint 142.1
    one: authorise, or scope the queryset, before answering. Audited and
    found CLEAN: `customers/serializers_labels.py` (customer is
    URL-bound and `_get_customer()` 403s first),
    `customers/serializers_contacts.py` (customer is `read_only`),
    `planned_work/serializers.py` (queries keyed on the ACTOR), and
    `tickets/serializers.py:1501` +
    `extra_work/serializers_messages.py:113`/`:201` (already query
    through `scope_tickets_for` / `scope_extra_work_for`).

22. **`seed_demo_data` seeds the catalog for one company and the demo
    Extra Work for another.** `_seed_service_catalog()` pins its 4
    categories + 14 services to `Company.objects.order_by("id").first()`,
    while `_seed_demo_extra_work` resolves its tenant by
    `slug="osius-demo"`. On a multi-company dev DB those are different
    companies, so the seeded `CustomerServicePrice` links a customer
    under one provider to a service owned by another — a shape
    `CustomerServicePriceSerializer` REJECTS over the API
    (`service_customer_company_mismatch`); the seeder only gets away
    with it by writing through the ORM. This predates Sprint 142 and was
    deliberately not fixed there: making the two agree re-targets the
    seeded catalog to a different company than existing dev DBs already
    have it under, which duplicates rather than moves it. Sprint 142
    narrowed the demo-EW lookup to the CATALOG's company (so the
    now-per-company `category__name="Cleaning"` fallback cannot pick a
    foreign provider's category) and left the mismatch itself alone. The
    real fix is one company for both, plus a note on what an existing DB
    should do with the old rows.

23. **Five state writes still sit AFTER their refetch — consistency, not
    a bug.** Sprint 141 moved three such writes to BEFORE the refetch so
    they no longer depend on a network call that is allowed to fail, but
    left five structurally identical sites behind:
    `ServicesAdminPage.tsx:500`, `:740`, `:892`, `ManagedUnitsTab.tsx:183`
    and `CustomerPricingPage.tsx:488`/`:507`. They are harmless ONLY
    because the three refetch helpers are non-throwing by contract — the
    line after `await refreshX()` always runs today. That contract is the
    single thing keeping them correct, so the day someone makes a helper
    throw again, these five silently regress into Sprint 141 §1. Either
    move them ahead of the refetch like the other three, or make the
    non-throwing contract enforceable rather than conventional.
    *(Sprint 153 note: the new bulk-deactivate call site on
    `CustomersAdminPage` writes local state BEFORE its refetch, so it
    does not add a seventh. The five listed above are untouched.)*

24. **Customers have no address or city — so the list cannot have a City
    column.** (Found in the Sprint 153 recon.) The reference system the
    owner compares us against shows a City column on its customer list.
    Ours cannot: `Customer` has NO address fields at all — only
    `contact_email`, `phone` and `language`. Adding them is a model
    change plus a form change plus a real product decision: is a
    customer's address distinct from its buildings' addresses, or is
    "the customer's city" just the city of its primary building? A
    customer sits in many buildings (that is why Sprint 153 deleted the
    Building column), so the second reading has no single answer either.
    Not built; awaiting the owner.

25. **`User` has no phone field, so the Users and Employees lists cannot
    show one.** (Found in the Sprint 153 recon.) Only `StaffProfile
    .phone` (staff only) and `Contact.phone` (a phone-book row, not a
    login) exist. A non-staff user — a COMPANY_ADMIN, a
    BUILDING_MANAGER, a customer user — has no phone anywhere in the
    system. Shape if taken up: additive `User.phone` + migration + form
    field + list column, and a decision about whether `StaffProfile
    .phone` then becomes redundant or stays as the work number. Queued
    for the polish round.
    ***CLOSED by Sprint 154 §I.1/§K.*** `User.phone` shipped (additive,
    `accounts.0009`), with columns on the Users / Employees /
    Customer-users lists and an input on the user form. The decision on
    `StaffProfile.phone` was made and is NOT "redundant": it STAYS, as a
    genuinely different field. It is staff-only and its visibility is
    governed by `Customer.show_assigned_staff_phone` / the
    CustomerCompanyPolicy mirror, and `ProviderEmployeeSerializer`
    carries an explicit privacy floor forbidding it on the BM/CA read
    surface. The two are not merged and not mirrored into each other;
    every read site picks one explicitly.

26. **Five copies of the terminal-ticket-status set.** (Found in the
    Sprint 153 recon while wiring `open_ticket_count`.) The same four
    statuses (`APPROVED`, `REJECTED`, `CLOSED`,
    `CONVERTED_TO_EXTRA_WORK`) are declared independently in
    `tickets/models.py` (`TERMINAL_TICKET_STATUSES`, the exported one),
    `tickets/views.py` (`_SCHEDULE_TERMINAL_STATUSES`),
    `tickets/filters.py` (`_AGENDA_TERMINAL_STATUSES`),
    `tickets/views_manager_assignments.py` (`_TERMINAL_STATUSES`) and
    `sla/services.py` (`TERMINAL_STATUSES`). **All five currently
    agree**, and each carries a comment saying it mirrors one of the
    others — which is precisely the Sprint 126 headerless-column shape:
    a second independently-maintained copy that the compiler cannot
    check. Sprint 153 imported the exported one rather than adding a
    sixth. The fix is to collapse the other four onto
    `tickets.models.TERMINAL_TICKET_STATUSES`, checking each call site's
    intent first — `sla/services.py` additionally defines
    `PAUSED_STATUS` and may genuinely mean something narrower.
    *(Sprint 154's `buildings/views_summary.py` imported the exported
    `tickets.models.TERMINAL_TICKET_STATUSES` rather than adding a
    seventh copy. Still five.)*

27. **This system has no ROOM concept, and §I.6 asked for a room
    count.** (Found in the Sprint 154 recon.) There is no `Room` model,
    no rooms app, and no field subdividing a `Building` — it is an
    indivisible location everywhere: tickets, extra work, planned work
    and staff visibility all anchor on `building_id` with nothing below
    it. `GET /api/buildings/<id>/summary/` returns `room_count: null`
    unconditionally so the contract is stable and the UI renders an em
    dash rather than a misleading `0`. If the owner wants rooms it is a
    new model, a migration, and a product decision about what a room
    means for ticketing and for staff visibility — not something to
    infer from a stat tile.

28. **Two i18n bundles, one namespace default, and no check that
    catches the gap.** (Found by MEASURING in Sprint 154 §N.2.) The
    §P i18n gate compares `nl/common.json` against `en/common.json`
    only. That is a lockstep check BETWEEN LANGUAGES; it says nothing
    about whether a key is in the bundle the calling page actually
    reads. `ExtraWorkListPage` defaults to the `extra_work` namespace,
    `list.filter_catalog_category` lived only in `common.json`, and the
    raw key rendered on screen for at least a sprint while the gate
    stayed green. Fix shape: a check that every `t("...")` literal in a
    page resolves in one of the namespaces that page passes to
    `useTranslation`. Cheap to write, and it closes a class of bug the
    current gate is structurally blind to. Note the other seven bundles
    (`extra_work`, `dashboard`, `tickets`, ...) are not lockstep-checked
    between languages at all either.

29. **The two sortable-header components are duplicated verbatim.**
    (Sprint 154 §E.) `CustomersAdminPage` and `BuildingsAdminPage` each
    define an identical `SortableHeader` plus the same
    `sortStateFor` / `handleSort` trio. They were kept separate because
    their `SortField` unions are page-specific and TypeScript checks
    each against its own endpoint's `ordering_fields`; a shared generic
    would either lose that or need a type parameter threaded through
    every call site. Worth extracting when a THIRD list needs sorting —
    two copies is a coincidence, three is a pattern, and the Sprint 126
    lesson applies from there on.

30. **A COMPANY_ADMIN in more than one provider company gets an
    unfiltered candidate list on the building detail Add pickers.**
    (Sprint 154 §G.2.) `listAllUsersByRole` fetches every
    BUILDING_MANAGER / STAFF the caller may administer, which for a
    multi-company CA spans all their companies. The bulk-link endpoint
    still refuses anything out of scope, so nothing unsafe can be
    created — but the picker offers names from a company that has
    nothing to do with the building being edited. Fix shape: pass the
    building's `company` to the candidate fetch. Same family as NEXT
    item 0.

---

## SHIPPED

Append-only, one line per merged PR, newest first. #100–#114 are the
original record — wording preserved as shipped; #115 onward extends it
(Sprint 122.1). The old heading here cited `git log --oneline master` —
stale, since PR #116 renamed the default branch to `main`.

- **#130** (`a7c37f6`) — Sprint 152 plus rounds 152.1–152.3: employee
  hours (urenregistratie) as a new, INDEPENDENT `timesheets` app at
  `/api/timesheets/`, with the architectural rule held throughout — **no
  FK to and no import from Tickets, Extra Work or Planned Work**, in
  either direction. Three models on one additive migration (`HourType`,
  `TimeEntry`, `WeekLock`), with `WeekLock`'s invariant that the ABSENCE
  of a row means the week is open, so nothing is pre-created and nothing
  needs backfilling for a new company. The immutability core is
  `multiplier_snapshot`: every weighted computation reads the snapshot,
  never the live multiplier, and editing a type refreshes it only on
  OPEN weeks of that company. `iso_year`/`iso_week` are derived in
  `save()` and never client-supplied, so no write path can produce a row
  whose stored week contradicts its date. 152.1 fixed the round's
  company resolution; 152.2 turned the Weeks tab into an Overview tab;
  152.3 stopped the standard hour types being duplicated and unified the
  hour-type label rule across twelve call sites.
  **⚠ #130's CI NEVER RAN.** A GitHub Actions outage on 2026-08-06/07
  dropped the webhooks and the owner merged without a completed run, so
  **the full backend suite has never executed against Sprint 152's
  code**. Sprint 153's PR is the first real regression run for it — read
  any failure there as a candidate #130 regression before assuming it
  belongs to #131.
- **#128** (`6a93e77`) — Sprints 142 through 151.1 on one branch, one PR:
  eleven rounds on the catalog and its customer-facing side. **142** made
  `ServiceCategory` per-company (`company` FK + `UniqueConstraint(Lower(
  Trim(name)), company)`, migrations 0023–0025 with an ABORTING backfill
  rather than a guessing one), which closed a live H-1 read leak — category
  GET is open to any authenticated user and `filter_categories_for` was the
  IDENTITY, so every customer of every provider could enumerate every
  provider's category names. Category writes moved off the SUPER_ADMIN-only
  gate onto `_enforce_catalog_management`, finally making
  `provider_admin_may_manage_catalog`'s help text true. **142.1** found the
  sprint had re-opened the same leak on the WRITE path: the new friendly-400
  uniqueness pre-check ran an UNSCOPED sibling query, so the status code
  alone reported whether a rival owned a name (400 = yes, 403 = no) and the
  400 body named it back — and `ManagedUnitSerializer` had carried the
  identical shape since Sprint 123. Both fixed via `_scoped_siblings`, and
  verified by REVERTING the fix and watching the oracle tests fail with the
  rival's name in the body. **143** shipped customer price folders and undid
  the setState-in-effect resync that locked the Extra Work form to one
  building. **144** collapsed the form's TWO "Category" controls into one
  (two nullable PROTECT FKs; the enum column untouched). **145–148** gave
  the customer's side its own vocabulary and stopped
  `ServiceListCreateView` handing every customer the provider's whole
  catalog — a client-side filter is "not shown", not "cannot reach".
  **149–150** established that a SUPER_ADMIN works in ONE provider company
  at a time, defaulting to the lowest-id tenant and remembering the
  operator's last choice. **151/151.1** resolved the four CI failures; all
  four were tests still encoding rules the owner had deliberately changed,
  **none was a behaviour defect.**
- **#127** (`91230a0`) — Sprints 137, 138, 139, 140 and 141 on one branch,
  one PR: five review rounds on the same body of work, each round found by
  the owner or the PM verifying the one before it. **Round 1 (137)**:
  multi-attachment tickets; archived customer prices hidden behind a
  toggle; the "copy from defaults duplicates" report resolved as NOT a
  duplication bug; the customer-pricing category drill-down; the Extra Work
  cart's real catalog-category filter; orderable `CustomerCustomPrice`
  lines; iOS-style bulk edit mode on three lists. **Round 2 (138)** — the
  interface offered actions that cannot succeed: `Service.has_price_rows`
  (one `Exists` annotation) so a priced row offers Deactiveren instead of a
  Delete that always 400s; category archive cascades to its services in one
  transaction and unarchive restores the category ONLY, reporting how many
  services stayed archived; bulk move-to-category; archived PRICE rows made
  unselectable and action-free; the archived toggle made to reflect its own
  state; copy-from-defaults grouped by category; the Extra Work filter bar
  re-laid-out and MEASURED (3 ragged rows → 2 flush rows at 1280px, 0px
  overflow). **Round 3 (139)** — four consistency defects: inactive
  services and units hidden by default behind the same toggle prices
  already had; success banners routed through the existing `ToastProvider`
  (4s success, sticky errors) while failure banners deliberately stayed
  in-page; `CategoryGroupedPicker` + `buildPickerGroups` extracted and all
  three bulk pickers moved onto it; the company dropdown made to actually
  filter the Services and Units lists via `?company=`, applied BEFORE
  `filter_services_for` so it can only narrow. **Round 4 (140)** — the
  lists contradicted their own toggle in five places; local merging
  abandoned in favour of one `refreshCatalogRows()` / `refreshUnits()` /
  `refreshPricingRows()` per page that honours the toggle and the company
  filter; the Units detail panel gained the Activeren/Deactiveren control
  its own hint text had been promising. **Round 5 (141)** — the failure
  paths round 4 never audited: five bulk handlers could wedge a dialog
  inert until reload, and a committed write could be reported as a failure
  whose retry created a REAL duplicate active price row (those tables have
  no uniqueness constraint by design). Fixed once, in the three refetch
  helpers, which are now non-throwing by contract — not at thirteen call
  sites. Standing rule recorded: whenever a synchronous state update
  becomes an `await`, audit the throw path.
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

(There is no I-7. It recorded `ServiceCategory` staying global as
intentional; Sprint 142 reversed that decision and removed the entry
rather than leave it contradicting the code. The reversal is recorded in
`## NOW` / `## SHIPPED`, which is where decisions live — this section is
only for behaviours a future audit should NOT re-flag.)

---

## Moved to `docs/archive/` in Sprint 122.1

Purely historical build logs that no live work still references by
number — moved out rather than kept here. Each carries the standard
`ARCHIVED` banner; each is also listed in `docs/README.md`'s Archive
section.

- [`archive/2026-06-sprints/meeting2-and-early-sprints.md`](../archive/2026-06-sprints/meeting2-and-early-sprints.md) — Sprint 0–9, the Ramazan-Meeting-2 near-term block (CP, M1–M7), and the 2026-06-23 phase-order roadmap.
- [`archive/2026-06-sprints/invoicing-build-log.md`](../archive/2026-06-sprints/invoicing-build-log.md) — the invoicing subsystem's Phase 1–5 build log (superseded by [`sot-addendum-b-invoicing.md`](../product/sot-addendum-b-invoicing.md)).
- [`archive/2026-06-sprints/sprint-116-119-build-log.md`](../archive/2026-06-sprints/sprint-116-119-build-log.md) — Sprint 116 (CCA policy binding), Sprint 118 (the frozen-screen bug, root-caused and fixed), and Sprint 119 (credential PDF modal + known-issues, with the K-1/K-2 findings corrected to reflect their actual Sprint-120 fix).
