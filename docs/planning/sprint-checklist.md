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

**Branch:** `feat/sprint-122` — Sprints 122, 122.1 (this restructure), 123,
and 124 all land here; the owner opens **ONE** PR after Sprint 124.
**Last shipped PR on `main`:** **#118** — Sprint 121 (a Sprint-117
padding-regression fix on `BoundedList`, the nginx `.mjs` MIME-type fix
that had silently broken PDF-thumbnail rendering in prod, and PDF
first-page thumbnails for staff credentials).
**In flight on this branch (unmerged):**
- **Sprint 122** (commits `3933cd4`, `ff386a0`, `616cbc5`) — sharper PDF
  thumbnails (measure the parent tile + devicePixelRatio instead of the
  always-0 hidden-canvas width), the credit-note flow completed (an
  unmissable send-nudge on an unsent reversal, `credited_by_number` on
  both the provider and customer invoice views, and a fix for the Unissue
  button rendering on a reversal where the backend already rejects it),
  and a SUPER_ADMIN per-company **email** notification opt-in separate
  from the existing in-app subscription.
- **Sprint 122.1** — restructured this file into NOW/NEXT/SHIPPED and
  closed the anti-drift gap (see above).
- **Sprint 123** — managed units per provider company. A new
  `extra_work.ManagedUnit` model (company-scoped, case+whitespace-
  insensitive unique label, `is_active` archive flag) plus a nullable
  `managed_unit` FK on `Service` and `CustomerCustomPrice` (additive
  migrations `extra_work/0018`–`0020`: the schema, a data backfill that
  collapsed every existing distinct-normalized free-text
  `custom_unit_label` per company into one managed unit (most-frequent-
  spelling-wins, tie-broken by earliest `created_at`), and a trailing
  help-text-only field alter). Admin CRUD at
  `/api/services/units/`, gated on the same catalog-management
  permission as the Service catalog, tenant-scoped like every other
  catalog endpoint. Frontend: a new "Units" tab on the Services admin
  page, and a shared `ManagedUnitPicker` (active-unit dropdown + inline
  "add new") replacing the free-text input everywhere `unit_type ==
  OTHER` is chosen for a `Service` or a `CustomerCustomPrice` — **not**
  for `ProposalLine`, which stays deliberately frozen free text (a
  proposal is a document already shown to the customer; repointing it at
  a catalog that can later be renamed would silently change a historical
  quote). Deliberately NOT added to `## SHIPPED` yet — this branch is
  still unmerged and has no PR number.
**Immediate next sprint:** **Sprint 124** — per-building revenue split
in Customer Reports (see `## NEXT`).

---

## NEXT

Single ordered queue — replaces the four lists this used to be spread
across ("Owner's forward queue", "Deferred / undecided items", "Standing
milestones", "Deferred"). All four are now retired; every genuinely-open
item from them lives here, and every already-shipped or already-decided
item has moved to `## SHIPPED` or been resolved below instead.

1. **Sprint 124 — per-building revenue split in Customer Reports**
   (owner-decided: build it). Resolves the former "customer-scoped chart
   follow-ups (#109 Part H)" item, which had been listed as optional —
   now decided and queued, next up on this branch.
2. **SUPER_ADMIN "My Work" page content** — what should an SA see on a
   "my work" surface? An SA creates little of their own work; the
   concept today is admin-scoped. Awaiting the owner's definition before
   anything is built.
3. **Dashboard "Mijn werk" section purpose** — clarify whether the chip
   row means "items I created" (current behaviour) or a broader "what
   needs me" queue, and whether it should differ per role. Awaiting
   owner direction.
4. **Fixing & Auditing Sprint** — gated on Ramazan's full side-by-side
   review landing (his own commitment, not yet delivered as of
   2026-07-27). Scope once it lands: incorporate whatever further changes
   Ramazan + father want; pin down **RF-7** (the Extra Work
   pricing-area "big tabs" element he wants changed — location confirmed,
   exact element still to be pinpointed — see the appendix below); design
   + build the **Department + Event** section in person with Ramazan and
   father (no `Department` model exists in the codebase, confirmed
   2026-07-27); a full codebase audit (bugs / dead code / inconsistencies,
   confirm each shipped feature behaves as intended); reconcile this
   checklist against the real codebase once the audit lands.
5. **Mobile responsiveness** — gated on Ramazan's review landing (#4).
6. **Light/advanced mode split** — gated on Ramazan's review. Owner
   decision: this is an **architectural** decision to be settled BEFORE
   the Event/Department features are built, not a later styling pass.
7. **Event + Department features** — gated on Ramazan's review, designed
   in person with Ramazan and father (see #4).
8. **General code refactoring** (clean-up only, **no behaviour change**)
   — owner decision: happens AFTER Event/Department ship, not before.
9. **E2E Testing Sprint** — after Fixing & Auditing. Scope: Playwright
    coverage of the critical full-stack flows on the settled
    post-feedback system — auth/login, create ticket + melding, ticket
    lifecycle (staff complete → manager review → customer approval),
    extra-work request → proposal/instant → actual-hours finalize,
    customer pricing (contract / custom / bulk-raise / copy-default),
    notification deep-links. Token-inject pattern (the e2e login form is
    flaky). Green in CI. Ordering rationale (recorded 2026-06-23, still
    the plan): the Fixing & Auditing sprint reshapes the UI, so tests
    written first would be invalidated by those changes.
10. **Frontend Testing Sprint** — after E2E. Component/unit tests for
    high-value frontend logic that lacks coverage: pricing-amount
    display, active-priced-line selection, permission/visibility gating,
    the drill-in people/permissions flows, notification rendering.
    Establish the test runner + a CI gate; do not regress the ESLint
    baseline (48). No frontend component/unit test runner exists yet —
    backend `manage.py test` and Playwright e2e are the only test
    runners today; do not add an alternative opportunistically outside
    this planned sprint (CLAUDE.md §8).
11. **Production hardening → CD → Sentry.** Needs the owner's OWN input,
    not blocked on engineering: real SMTP credentials, a Sentry account +
    DSN, and the real production OSIUS company slug for
    `PLATFORM_BRAND_SLUG` (see `sot-addendum-b-invoicing.md` §B.9 — if it
    doesn't match, OSIUS's own invoices render unbranded). CD via GitHub
    Actions is otherwise ready to wire up (CI already runs as required PR
    checks). Also standing: TLS, non-root containers, Postgres backups.
    The owner will work through these interactively, not as an
    engineering-only backlog item.
12. **`reverse_invoice` never flips the original invoice's status** —
    found during Sprint 122 verification, re-verified 2026-07-27 directly
    against `backend/invoicing/state_machine.py`: `reverse_invoice`
    checks the original is `SENT` and is not itself a reversal, but never
    changes `original.status`, and `Invoice.reverses` carries no
    uniqueness constraint — so nothing stops the same SENT invoice being
    reversed more than once, each time minting another negated
    counter-invoice (with its own real, gapless number) against the same
    original. Pre-existing, not introduced by Sprint 122. No decision yet
    on whether/how to guard it — recorded so it isn't lost.
13. **Admin-picker lists sit on the DRF 200-row page cap** — found while
    verifying Sprint 120's pagination fix (commit `79d814d`): confirmed
    `CompanyViewSet` / `CustomerViewSet` / `BuildingViewSet` have no
    `pagination_class` override, so the roughly dozen admin-page call
    sites requesting `page_size: 200` (company/building/customer/user
    picker and candidate lists) would silently truncate for any tenant
    exceeding 200 rows — the same shape Sprint 120 fixed for the EW/
    invoice/dashboard/reports lists. The Sprint 120 commit message
    explicitly flagged this as future work but it was never added to this
    file until now. Not urgent at current data volumes.
14. **Add the Sprint 118 `<dialog>`-unmount gotcha to
    `docs/engineering/claude-code-operational-notes.md`** — found during
    Sprint 122.1: Sprint 118 root-caused and fixed the frozen-screen bug
    (a native `<dialog>` left the document inert if a component unmounted
    without calling `close()` first — see
    `docs/archive/2026-06-sprints/sprint-116-119-build-log.md`), but that
    reusable engineering pattern was never added to the live operational
    notes doc. Small, standalone, docs-only.
15. **`ServicesAdminPage` never sends an explicit `company` on create** —
    found during Sprint 123: the Services/Categories/Units tabs all rely
    entirely on the backend defaulting a COMPANY_ADMIN's own membership
    (`_resolve_catalog_create_company`); a SUPER_ADMIN managing a tenant
    with 2+ provider companies (the dev seed has 3) cannot create a
    Service, Category, or the new managed Unit through this page at all —
    every create 400s asking to disambiguate, with nowhere in the UI to
    supply one. Pre-existing for Service/Category (Sprint 123's Units tab
    just inherited it verbatim for consistency, deliberately, rather than
    solving it once for the new surface only). Not urgent — SA-managed
    multi-company catalog administration doesn't seem to be a current
    workflow — but a company selector on this page would fix all three
    tabs at once whenever it's prioritized.
16. **`ServiceCategory` is global while the new `ManagedUnit` is
    per-company** — found during Sprint 123 (explicitly out of scope to
    "fix" there): `ServiceCategory.name` is unique system-wide with no
    `company` FK, while `Service`, `CustomerCustomPrice`, and now
    `ManagedUnit` are all company-scoped. Pre-existing inconsistency
    (predates Sprint 123), recorded so a future sprint touching either
    catalog doesn't have to rediscover it. No decision on whether it's
    worth reconciling.

---

## SHIPPED

Append-only, one line per merged PR, newest first. #100–#114 are the
original record — wording preserved as shipped; #115 onward extends it
(Sprint 122.1). The old heading here cited `git log --oneline master` —
stale, since PR #116 renamed the default branch to `main`.

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
6. **Customer "event" + "department" fields.** On customer create, possibly two more dropdowns: event + department. Department likely customer-specific. "Event" may be a selectable event type, not a category — undecided. **Still open — see `## NEXT` #8.**
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

**RF-7 — Extra Work detail: pricing section "big tabs" (Ramazan, 2026-06-23; location confirmed, element TBC).** Big tab/block elements where he prefers click-in navigation. Göktuğ confirms it's the EW pricing section; the exact element is still to be pinpointed. **Still open — see `## NEXT` #5.**

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

**Owner review round 5 (2026-07-20):** "My Work" made role-adaptive and hidden for SA + CA. **Shipped — `## SHIPPED` #111.** Two open discussion items from this round are carried in `## NEXT` (#3, #4).

**Meeting notes (2026-06-23):** Department/event are category-like fields; names must stay editable/customer-flexible — refines backlog #6. Ramazan will do a full side-by-side review vs their current system (this is the review `## NEXT` #5 is gated on). He validated the pricing work (bulk raise, customer-specific prices, price history preserved). The credentials/permissions area of their current tool is their worst pain point.

## Documented-intentional behaviors (audit 2026-07-20)
These surfaced during the #109 audit and are intentional — recorded so a future audit does not re-flag them:
- **(I-1)** The ticket-level `/tickets/<id>/unable-to-complete/` endpoint is superseded by the slot-completion flow (AgendaPage → `send_slot_unable_to_complete_email`) and is intentionally left unsurfaced.
- **(I-2)** The legacy `ExtraWorkPricingLineItem` route is alive by design (older EWs keep it) and has no `actual_hours` column by design — it never gates the completion transition.
- **(I-3)** The SA notification feed is empty by design (the in-app fan-out deliberately excludes unsubscribed SUPER_ADMIN; only directed messages reach them) — opt-in per company (`## SHIPPED` #109), with a separate email opt-in added in Sprint 122.
- **(I-4)** `clear-invoiced` clears by the EW's CURRENT billing month (COALESCE(invoice_date, spawned-ticket completion)), not the month it was originally marked in.
- **(I-5)** The customer logo GET is open to any authenticated user by design; writes are gated (a customer's logo only by that customer's CUSTOMER_COMPANY_ADMIN; SA may change any).
- **(I-6)** The user profile-photo GET is open by design; writes are self/SA only.

---

## Moved to `docs/archive/` in Sprint 122.1

Purely historical build logs that no live work still references by
number — moved out rather than kept here. Each carries the standard
`ARCHIVED` banner; each is also listed in `docs/README.md`'s Archive
section.

- [`archive/2026-06-sprints/meeting2-and-early-sprints.md`](../archive/2026-06-sprints/meeting2-and-early-sprints.md) — Sprint 0–9, the Ramazan-Meeting-2 near-term block (CP, M1–M7), and the 2026-06-23 phase-order roadmap.
- [`archive/2026-06-sprints/invoicing-build-log.md`](../archive/2026-06-sprints/invoicing-build-log.md) — the invoicing subsystem's Phase 1–5 build log (superseded by [`sot-addendum-b-invoicing.md`](../product/sot-addendum-b-invoicing.md)).
- [`archive/2026-06-sprints/sprint-116-119-build-log.md`](../archive/2026-06-sprints/sprint-116-119-build-log.md) — Sprint 116 (CCA policy binding), Sprint 118 (the frozen-screen bug, root-caused and fixed), and Sprint 119 (credential PDF modal + known-issues, with the K-1/K-2 findings corrected to reflect their actual Sprint-120 fix).
