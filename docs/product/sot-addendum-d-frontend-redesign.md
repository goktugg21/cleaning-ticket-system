# Osius — Source of Truth · Addendum D (Frontend Redesign) — DRAFT

**Date:** 2026-08-28. **Status: DRAFT — requires owner + Ramazan sign-off
before any implementation.** Once signed off, this Addendum wins over the
base SoT §16 (frontend baseline / UI backlog) for the items it covers.
Where this doc and the code disagree, the code is the truth — report the
drift.

**Evidence base:** full read of the live docs (base SoT, Addenda A–C, RBAC
matrix, business-logic doc), backend model/view inspection (14 apps, ~90
models), frontend inspection (267 TS/TSX files, ~70 routes, single
10,476-line `index.css`), and a **visual review of 33 rendered screenshots
across four roles** (Provider Admin, Building Manager, Staff, Customer)
captured from a locally running stack seeded with `seed_demo_data`.

**Scope:** presentation, information architecture, vocabulary, and flows.
This Addendum changes **no business rule, no permission, no state machine,
no money rule**. Backend work is limited to additive, presentation-only
serializer fields (§D.4).

Items marked **DECISION** need an explicit choice by the owner/Ramazan
before the sprint that touches them. Everything else is proposed as
default-approved once this document is signed off.

---

## D.0 The one-sentence goal

Every screen must answer, in the viewer's own vocabulary and at first
glance: **"What is this? What happens next? What is the ONE thing I can do
here?"** — for a viewer who is not a programmer and has never read the
docs.

The two internal proofs that this is achievable in this codebase, to be
used as the pattern references for every surface:

1. **The customer Permissions page** — plain-language module toggles on
   top, "Advanced" (per-permission policy, technical keys, per-user
   exceptions) collapsed underneath.
2. **The staff Werkplanning page** — task cards per day with the primary
   action ("Voltooid melden") on the card. (Its *underlying scheduling
   behaviour* has a suspected functional gap — see §D.8. The pattern
   reference is the card/action shape, not the current behaviour.)

---

## D.1 Diagnosis — five root causes (condensed)

1. **One interface for four audiences.** Customers get the operations
   console: the header says "Operationele console", the melding and
   extra-work forms ask the customer to select their own *Klant*, the
   extra-work form shows a **"Gefactureerd aan"** field, and the customer
   dashboard shows a **"Niet toegewezen"** tile (a provider concept). The
   customer extra-work form is identical to the provider's ~13-field form.
2. **Vocabulary sprawl.** Seven overlapping work words: Melding → Ticket →
   Extra werk → *Chargeable work / Meerwerk* (an EW-origin ticket) →
   Werkplanning (the agenda) → Terugkerend werk → occurrences (which spawn
   tickets). NL itself is split: "Extra werk" vs "Meerwerk" for the same
   concept in different corners of the UI. Internal machinery leaks into
   copy: "Routing: Proposal — awaiting pricing review", a primary button
   "Retry scheduling work", a permanent list tab "Reopened by admin".
3. **Forms ask everything at once.** EW create: ~13 decisions incl. THREE
   date fields (Preferred / Planned end / Deadline). Recurring-job form
   requires understanding time windows with per-window pricing
   inheritance. Melding create requires two separate description fields
   plus an SLA priority choice.
4. **Screens show every state dimension at equal weight.** EW detail shows
   "Price approved" + "Proposal" + routing text + billing-month override +
   spawn state simultaneously; Ticket detail collapses "Ticket details" by
   default while a four-pill message composer dominates.
5. **Navigation + craft.** ~21 admin nav items; a wholesale nav-swap when
   entering a customer ("Beperkt tot" mode); two similarly-named planning
   entries ("Werkplanning" vs "Terugkerend werk" — EN "Work plan" vs
   "Recurring work"); dashboard right column overflows at 1440px; a toast
   covers the "Convert to Extra Work" button; tables overflow
   horizontally; NL/EN mixing on one screen.

**Explicit non-finding:** the backend does NOT need reorganising for this.
The `actions.can_*` / `allowed_next_statuses` contracts and the one-EW →
one-operational-ticket spawn model are exactly what a simple UI needs.

---

## D.2 Vocabulary — one name per concept

Rule: **nl is primary** (existing i18n rule). One name per concept,
everywhere: nav, page titles, pills, notifications, PDFs, audit copy.
A concept whose name cannot be explained to a cleaner in one sentence is
misnamed.

| Concept (internal/backend) | NL (user-facing) | EN (user-facing) | Notes |
|---|---|---|---|
| Customer-created REPORT ticket | **Melding** | Report | Unchanged. Customers only ever see "melding". |
| Provider operational ticket | **Ticket** | Ticket | Provider-side word only. Customers never see "ticket". |
| Extra work request (commercial object) | **Meerwerk** | Extra work | **DECISION:** standardise on *Meerwerk* (matches Ramazan's real invoices — "3 meerwerken", Addendum B §B.12) and retire "Extra werk" as a label, or the reverse. Mixed usage is not an option. |
| EW-origin operational ticket ("chargeable work") | **Meerwerk — uitvoering** (as a phase, never a separate noun) | Extra work — execution | **KILL the standalone name "Chargeable work".** It is the same meerwerk in its execution phase (§D.4). The provider queue keeps a type pill; the nav entry "Chargeable work" is removed (its list becomes a filter of the work queue). |
| Staff/BM agenda (`/agenda`) | **Werkplanning** | My schedule | EN "Work plan" is retired to end the "Work plan vs Recurring work" pair. |
| Recurring job templates (`/planned-work`) | **Terugkerend werk** | Recurring work | Unchanged. |
| Occurrence | **Geplande beurt** (or "bezoek") | Planned visit | **DECISION:** pick the word Ramazan's people actually say. Never "occurrence" in UI. |
| Proposal / quote | **Offerte** | Quote | "Proposal" disappears from user-facing copy; internal model name stays. |
| Notes: public reply / internal / operational / completion | Reactie / Interne notitie / Werkinstructie / Afrondingsnotitie | Reply / Internal note / Work instruction / Completion note | Composer shows only the types the viewer can use, with one-line "who sees this" captions (already partly done). |

**Banned in user-facing copy:** routing, proposal (EN), spawn, operational
ticket, occurrence, slot, scope, policy key, "Retry scheduling work",
"Reopened by admin" (as a tab — it becomes a badge inside history), any
sentence that names a backend mechanism.

---

## D.3 Roles and navigation

Principle: **role-based defaults + progressive disclosure**, not two
maintained frontends. "Light vs Advanced" = what a role sees by default vs
what unfolds behind an "Advanced" affordance on the same screen (the
Permissions-page pattern). The Advanced layer obeys the same one-decision-
at-a-time rules.

### D.3.1 Customer (CU / CLM / CCA — provider role CUSTOMER_USER)

Nav (6 entries, fixed order):

1. **Start** — "my open items" only: my meldingen in progress, meerwerk
   waiting on MY decision (approve price / approve completion), unread
   messages. No provider KPIs, no "Niet toegewezen".
2. **Melding maken** — the 3-field flow (§D.5.1).
3. **Mijn meldingen** — list + detail with phase timeline.
4. **Meerwerk** — request (guided flow, §D.5.2) + track (one object per
   request, phase timeline; the spawned ticket is NEVER shown as a
   separate item).
5. **Facturen** — SENT invoices (existing scope).
6. **Medewerkers / Documenten / Instellingen** — grouped under "Meer"
   (**DECISION:** or keep flat at 8 entries; default proposal is the
   "Meer" group).

The word "console" and the provider company branding header disappear from
the customer surface; it is "<Provider name> — Klantportaal".
Auto-selections: Klant is never asked (derived from membership); Gebouw is
pre-selected when the user has exactly one.

### D.3.2 Staff (STAFF)

Nav (4): **Werkplanning** (landing page — not Dashboard), **Mijn uren**,
**Berichten**, **Instellingen**. The staff Dashboard route redirects to
Werkplanning. Notifications merge into Berichten for staff (**DECISION** —
merging the bell feed and message inbox for staff only; provider roles
keep both).

### D.3.3 Building Manager (BUILDING_MANAGER)

Nav (~8): Werkplanning (their managed tickets), Werk (queue), Meerwerk,
Terugkerend werk, Uren, Rapporten, Berichten, Instellingen. Invoices stay
read-only reachable from customer context, not top-level (**DECISION**).

### D.3.4 Provider Admin / Super Admin

Four groups, entries collapsed from ~21 to ~12:

- **Werk:** Dashboard, **Tickets** (the work queue: tickets +
  meerwerk-execution with type pills; "Chargeable work" becomes a saved
  filter — **owner decision 2026-08-29: the queue keeps Ramazan's word
  "Tickets" in BOTH locales, never "Werkqueue" / "Work queue"**), Meerwerk
  (commercial pipeline: quotes/pricing/approvals), Terugkerend werk.
- **Financieel:** Facturen, Contracten, Uren.
- **Klanten & mensen:** Klanten, Gebouwen, **Mensen** (Users + Employees +
  Invitations merged into one surface with tabs — **DECISION**),
  Medewerker-aanvragen (badge-driven, hidden when empty).
- **Systeem:** Diensten & catalogi (merged), Bedrijven (SA), Auditlog
  (SA), Instellingen.

**Customer scoped mode:** the wholesale left-nav swap ("Beperkt tot") is
replaced by a persistent global nav + an in-page customer header with tabs
(Overzicht / Gebouwen / Mensen / Permissies / Prijzen / Contracten / Werk /
Facturen / Documenten / Instellingen). One navigation system, no mode.
(**DECISION** — this is the largest IA change; alternative is keeping the
swap but with a permanent, unmissable return affordance.)

---

## D.4 The Meerwerk presentation model

Backend stays as is. What changes is presentation, backed by ONE additive
backend field so the frontend never infers (SoT §11.1):

- **`display_phase`** (read-only, computed server-side per viewer) on the
  EW serializer, collapsing intent + status + routing + spawn state +
  approval state into one value from a short enum, e.g.:
  `WAITING_PRICE`, `WAITING_YOUR_APPROVAL` (customer) /
  `WAITING_CUSTOMER_APPROVAL` (provider), `SCHEDULED`, `IN_EXECUTION`,
  `WAITING_COMPLETION_APPROVAL`, `DONE`, `INVOICED`, `REJECTED`,
  `CANCELLED`. Exact mapping table to be locked in the sprint that builds
  it, derived from the existing state machines — the enum is
  presentation-only and MUST NOT become a writable state.
- **Requester view = one object.** A customer (or provider acting for
  them) follows one "meerwerk" with a phase banner + a vertical timeline
  (requested → priced → approved → scheduled → carried out → approved →
  invoiced). The spawned ticket's events are folded INTO that timeline.
  The requester never sees a second object called "ticket".
- **Provider ops view = the queue.** Tickets and meerwerk-execution share
  the work queue with an unmissable type pill and origin link (SoT §1.4
  unchanged). The pill text follows §D.2 (no "Chargeable").
- Detail pages lead with a **fact block** (what, where, who, when, phase)
  and ONE primary action from `actions.can_*`; correction/override actions
  live behind "Geavanceerd" with the existing warning/audit surfaces.
  "Retry scheduling work" and similar recovery actions move behind
  Advanced with human copy ("Opnieuw proberen in te plannen") and only
  render when actionable.

**Verdict on a separate "Extra Work Ticket" model (owner question,
2026-08-28): NO new model.** The structure already exists —
`Ticket.extra_work_request` (related_name `operational_tickets`) makes an
"extra work ticket" a Ticket with a non-null parent. A second model would
duplicate the state machine, staff assignments/slots, sub-tasks,
messages, attachments, hours, SLA and audit wiring — the exact
duplication the original design avoided — and `tickets/work_plan.py`
already demonstrates the ongoing cost of normalising two parallel models.
Instead the kind becomes **first-class in presentation**:

- Additive serializer field **`kind`**: `MELDING` (customer REPORT) /
  `MEERWERK` (has parent EW) / `TICKET` (other provider work), computed
  server-side (same pattern as `display_phase`, never client-inferred).
- The work queue shows meerwerk-execution **by default, with an
  unmissable "Meerwerk" pill** linking to the parent (replacing the
  opt-in "Include chargeable work" toggle + separate nav page).
- The same execution work stays visible **inside** the parent meerwerk's
  timeline (§D.4 requester view) — both places, one record, zero
  duplication.

---

## D.5 The five core flows (target shapes)

Step counts are the acceptance criterion; a flow that grows a step needs a
reason written next to it.

### D.5.1 Report a problem (customer melding)

3 visible questions: **Waar** (building/zone — pre-selected when only
one), **Wat is er aan de hand** (ONE description field), **Foto**
(optional). Urgentie: default Normaal, one tap for "Spoed". SLA copy,
priority matrix, asset-ID guidance, and the second required description
field are removed (detailed description merges into the one field).
Submit → confirmation with the phase timeline and "wat gebeurt er nu".

### D.5.2 Request meerwerk (customer, and provider-on-behalf)

Guided short flow, one decision per step, intent DERIVED not asked:

1. **Waar** (building; pre-selected when only one).
2. **Wat** — service picker showing THEIR agreed prices (existing rule),
   plus "iets anders" free-text line for custom work.
3. **Wanneer** — ONE date wish field. (Planned end / deadline are
   provider-side planning fields and move to the provider's scheduling
   surface / Advanced.)
4. **Bevestigen** — the system STATES what happens next based on the cart
   (all agreed prices → "wordt direct ingepland"; any custom line → "u
   ontvangt eerst een prijs"), with the auto-start choice offered only to
   roles allowed by SoT §5.3. "Gefactureerd aan", Afdeling, Werktype,
   Categorie, Urgentie leave the customer flow (defaults + provider-side
   editing; **DECISION:** whether Afdeling/Werktype must remain a customer
   question for Ramazan's invoicing annex, or default per building and be
   corrected provider-side).

The separate nav entry "Offerte aanvragen" merges into this flow (the
quote path is a derived outcome, per SoT §5.1 validation rules —
navigation stops encoding intent).

### D.5.3 Price & approve

Provider: pricing worklist ("Wacht op prijs") → proposal builder
(existing) → send. Customer: ONE approval screen — the price, the lines,
Akkoord / Afwijzen (with reason), nothing else. Quote-bypass keeps its
danger surface unchanged (SoT §5.5).

### D.5.4 Execute & complete (staff)

Werkplanning card → open → fact block + werkinstructies first → "Voltooid
melden" (photo/note where required) or "Kan niet voltooien" (reason →
manager notified; SoT §4.4). Messages exist but never displace the facts.

### D.5.5 Invoice (provider)

Due panel ("wie is aan de beurt") → generate draft → review (page-1
summary + annex preview, Addendum B unchanged) → send. No new mechanics —
this flow is already close; the work is copy + layout + the §D.6 rules.

---

## D.6 UX principles (the design law for every sprint)

Owner-stated rules, codified. Every redesigned screen is checked against
this list before it is called done.

1. **Scroll means scroll.** No scroll-jacking, no effects that replace
   scrolling, no autoplaying motion. Calm surfaces.
2. **Actions appear where you clicked.** Dialogs/popovers anchor to their
   trigger; nothing opens in a far corner. Toasts NEVER cover actionable
   controls (top-right toast + top-right actions is the current bug —
   toasts move to a position audited per layout).
3. **One primary action per screen state.** Everything else is secondary
   or behind "Geavanceerd". Correction/override actions are always behind
   Advanced, always with their existing warning + audit surfaces.
4. **At most 5–7 visible choices at once.** More than that means the
   screen needs staging or an Advanced fold, not a longer page.
5. **Facts before conversation.** Detail pages open with the fact block
   (what/where/who/when/phase), never with a collapsed facts panel under
   an expanded composer.
6. **The child test.** For each of the five core flows, the sprint ends
   with a written walkthrough: what does a person who knows nothing about
   computers see at each step, and what could they misread? Blockers found
   there are sprint scope, not backlog.
7. **No dev copy, no machinery words** (§D.2 banned list). Empty states
   say what the page is for and offer the one obvious action.
8. **Nothing overflows.** No horizontal cut-off at 1280/1440; tables
   collapse to cards below their breakpoint; every server-fed list is
   bounded (existing BoundedList rule).
9. **One language per session.** UI chrome follows the user's locale;
   mixed NL/EN on one screen is a bug. (Demo seed data may stay Dutch.)
10. **Loading and mid-states are designed** — skeletons, not "Loading
    operational ticket data..." over an empty console.
11. **Progressive disclosure is the pattern, not a second product.** The
    Advanced layer must itself satisfy rules 1–10.
12. **The system talks like a person — every surface, admin and super
    admin included.** Dense, efficient screens for professionals; never
    a wall of technical values; the screen tells the reader where they
    stand and what happens next. Admin surfaces do NOT become multi-step
    wizards — efficiency stays. (Owner, 2026-08-29.)
13. **Empty columns do not render.** A table column, tile or row whose
    every value would be empty on this page is absent, not a column of
    dashes or blanks; an empty state is said once, in a sentence, never
    twice on one screen. (P-5 S4, 2026-08-30.)
14. **A disabled control says why.** Next to, under or on (`title`)
    every disabled button, one sentence names the condition — "this
    week is closed", "no hour types are set up yet" — so the reader
    knows what to change instead of what to press. (P-5 S4.)
15. **Placeholders never look like values.** A date, amount or text
    field that is not set reads as unset (faint, or a word), never as a
    grey value the reader could mistake for a filled-in one; the
    filled-in state is visibly different. (P-5 S4.)

---

## D.7 Screen inventory — verdicts

(K = keep with copy/polish only, R = restructure on the same route,
M = merge into another surface, X = remove as a standalone surface.)

| Surface | Verdict | Note |
|---|---|---|
| Login / invite / reset | K | Fine. |
| Dashboard (provider) | R | One "needs attention" list + 3–4 KPIs; fix overflow; drop duplicate panels. |
| Dashboard (customer) | R | Becomes "Start" (§D.3.1): my open items only. |
| Tickets list | R | Work queue: 4 primary tabs (Open / Bezig / Wacht op klant / Afgerond), remaining statuses under a filter; analytics side panels move to Rapporten; fix table overflow. |
| Tickets: "Chargeable work" | X→M | Saved filter of the work queue; nav entry removed (§D.2). |
| Ticket create (provider) | R | Keep single page; one description field; room/type behind Advanced. |
| Melding create (customer) | R | §D.5.1 three-question flow. |
| Ticket detail | R | Fact block first; one primary action; messages second; overrides behind Advanced. |
| Extra Work list | R | Commercial pipeline grouped by display_phase. |
| EW create (provider) | R | Staged flow; the three date fields collapse to "gewenst" + Advanced planning fields. |
| EW create (customer) | R | §D.5.2. |
| Request-quote page | M | Into the §D.5.2 flow; nav entry removed. |
| EW detail | R | §D.4 phase banner + timeline; billing-month override behind Advanced. |
| Recurring work list/detail/calendar | K/R | Calendar model stays; copy pass; occurrence wording per §D.2. |
| Recurring job form | R | Staged: what → when (windows explained as "visits per day") → pricing → crew; per-window pricing behind Advanced. |
| Werkplanning (staff/BM) | K + investigate | Pattern reference; §D.8 behaviour investigation in the same sprint. |
| My hours / Hours admin / Contract hours | R (later) | Same principles; after core flows. |
| Reports | R (later) | Keep data; apply §D.6; EW reports stay separate (SoT §7). |
| Invoices / invoice detail | K/R | Close already; copy + §D.6 pass. |
| Contracts | K/R | Recent (Sprint 160); copy pass only for now. |
| Customers list/detail + scoped submenu | R | §D.3.4 in-page tabs replace nav swap (DECISION). |
| Customer pricing | R | Prices visible directly (category as filter, not a door); 6 header actions → 1 primary + menu. |
| Customer permissions | K | The pattern reference. |
| Users / Employees / Invitations | M | One "Mensen" surface with tabs (DECISION). |
| User detail | K | Recently polished; dedupe the two building lists; humanise per-building flag copy. |
| Services / Catalogs | M | One "Diensten & catalogi" surface. |
| Companies / Audit log / Staff requests | K | SA surfaces; copy pass. |
| Inbox / Notifications | K (R for staff) | §D.3.2 staff merge (DECISION). |
| Settings | K | Revisit last (base SoT §3.4 stands). |

---

## D.8 Known functional gaps to investigate (not visual)

1. **Werkplanning behaviour (owner-specified 2026-08-28):** resolved into
   the full behaviour spec in **§D.11** — carry-forward, deadline
   display, the unable-to-complete leak, and the billing-month guard.
   Implemented as sprint **WP-1** (see §D.9).
2. Mid-load states on the tickets list (console flash of unstyled data).
3. Toast placement vs top-right actions (Ticket detail).
4. Dashboard right-column overflow at 1440px; horizontal table overflow.
5. NL/EN mixing within one screen.

---

## D.9 Sprint plan (each: decide → implement → verify → owner review)

- **Sprint FE-0 — sign-off.** Resolve every DECISION in this doc with
  Ramazan; commit this Addendum + the docs/README.md index row + the
  CLAUDE.md patch (Appendix A). No code.
- **WP-1 — Werkplanning behaviour + billing guard (§D.11).** Runs FIRST
  after sign-off: it is business-critical (missed invoices) and
  independent of the visual redesign. Backend: `days_until_due`,
  follow-up rule for UNABLE_TO_COMPLETE, the billing-month at-risk
  endpoint + digest. Frontend: due-date/late chips on cards, the
  follow-up and at-risk lists. Tests extend
  `test_sprint179a_work_plan.py`.
- **FE-1 — vocabulary + navigation.** §D.2 renames, §D.3 nav regroup,
  remove nav-encoded intent entries. i18n lockstep maintained. Low risk,
  immediately visible.
- **FE-2 — customer surface.** Start page, melding flow, meerwerk guided
  flow + request tracker (needs `display_phase`, built here).
- **FE-3 — detail restructure.** Ticket + meerwerk detail: fact block,
  phase banner, one primary action, unified timeline, Advanced fold,
  toast fix.
- **FE-4 — staff surface.** Werkplanning polish + the §D.8.1
  investigation/fix.
- **FE-5 — provider forms.** Staged EW create, recurring-job form,
  ticket create trim.
- **FE-6 — admin console density.** Work queue tabs, customers in-page
  tabs, Mensen merge, pricing page, craft fixes (§D.8.2–5).
- **FE-7 — reports/hours pass + full §D.6 audit** across all surfaces,
  mobile responsiveness (base SoT §3.5).

Rules: no sprint mixes a backend business-rule change with FE work;
`display_phase` is the only planned backend addition and ships with tests
in FE-2. ESLint baseline and i18n lockstep rules apply throughout.

---

## D.10 Verification protocol (bounded, budget-safe)

Screenshots are the DESIGN evidence; measured geometry remains the
standard for layout regression CLAIMS (existing CLAUDE.md rule — the two
complement, they do not conflict).

Per sprint, inside ONE Claude Code session:

1. Implement against this Addendum's target for that sprint.
2. **Self-verify visually:** run the dev stack, capture the changed
   surfaces for each affected role (Playwright screenshot script or
   browser tool), and check them against the sprint's acceptance
   checklist (drawn from §D.5 step counts + §D.6 rules).
3. **Bounded fix loop: at most TWO fix iterations** per checklist item.
   Anything still failing after two is REPORTED as an open item with its
   screenshot — never silently retried further. No unattended
   agent-vs-agent loops; no while-loops on the owner's usage budget.
4. Session ends with: branch pushed, checklist with pass/fail per item,
   screenshot set, open-items list.
5. **Owner gate:** the owner (with web-Claude verifying from origin, per
   CLAUDE.md §1) reviews before merge. The owner's review replaces any
   "second agent" — one implementing session + one cheap review pass
   beats two agents supervising each other.

---

## D.11 Werkplanning behaviour spec (carry-forward, dates, deadlines)

Grounded in the implemented rule (`tickets/work_plan.py`, Sprints
179A/184) and the owner/Ramazan intent stated 2026-08-28. The business
problem this section exists for: **work that is physically done (or
undone) but never marked/confirmed silently misses its billing month,
and invoices come out wrong until someone edits the database by hand.**
That must become impossible to miss.

### D.11.1 What is already implemented (and stays)

The week board draws from TWO sources normalised onto one card shape:
dated staff slots (`TicketStaffAssignment` — "the parts": a ticket may be
split into SubTasks and per-staff dated/time-windowed slots) and extra
work. Placement follows four rules, applied server-side:

1. A job appears in the week(s) its planned window covers — its home,
   whatever its status. September shows September's work.
2. A STARTED job also appears in the current week (marked
   "started"/"started early").
3. **A job past its due date and unfinished also appears in the current
   week, on TODAY's column, marked overdue with a day count.** `due` =
   the EW deadline, or (for a slot) its last planned day.
4. Untouched future work appears only in its planned week + the
   "upcoming" list; jobs with no date live in the "Nog niet gepland"
   list.

Rule 3 IS the carry-forward: an unfinished job re-appears on today,
every day, until someone finishes, reschedules, or cancels it.

**DECISION (Ramazan — the one core choice):** carry-forward stays
"appears on today, marked N days late" and does NOT silently rewrite the
planned date. Auto-moving dates would destroy the planning history,
break "September shows September's work", and hide HOW late something is
— the day count is the pressure. Rescheduling remains an explicit human
action (existing reschedule flow with reason). Confirm or override.

### D.11.2 The gaps to close (sprint WP-1)

- **G1 — the "unable to complete" leak.** A slot marked
  UNABLE_TO_COMPLETE maps to BLOCKED, which counts as closed — it stops
  carrying forward and silently leaves the system's attention. Spec: a
  blocked job enters a **"Vastgelopen — actie nodig"** follow-up list
  (work plan + manager dashboard) and stays there until a human
  reschedules it, reassigns it, or cancels the work. Blocked ≠ done.
- **G2 — dateless work never nags.** A job with no planned date and no
  deadline can never become overdue by design (inventing dates is
  worse). Spec: "Nog niet gepland" gains an age indicator ("staat hier
  al N dagen") and is counted in the manager's needs-attention number.
- **G3 — deadlines and time-remaining are not shown.** The API exposes
  `due_date` / `is_overdue` / `overdue_days` but nothing renders
  "deadline over X dagen" before the fact, and `days_until_due` does not
  exist. Spec: additive `days_until_due` on work-plan entries; every
  card with a due date shows ONE chip: "over N dagen" / "vandaag" /
  "N dagen te laat" (colour-stepped). Vocabulary: user-facing word is
  **deadline** only where a real deadline exists (EW); a slot's date is
  its **geplande dag** — the chip copy must not call a planned day a
  deadline.
- **G4 — the billing-month guard (Ramazan's actual pain).** Completion
  is a chain: slot done → ticket completed (staff completion + manager
  confirm) → EW completed → billing month set → unbilled pool → invoice.
  A break anywhere (typically: manager never confirms) silently drops
  the job out of that month's invoice. Spec, additive:
  - An **"Deze factuurmaand loopt risico"** list on the invoicing due
    panel and provider dashboard: per customer, work whose planned
    day/deadline falls in the open billing month but whose chain is not
    complete (slot done but ticket unconfirmed; ticket stuck in manager
    review N+ days; EW in execution past deadline; blocked and
    unresolved), each row with its stuck-stage and age.
  - A weekly digest notification to admins listing the same (existing
    notification infrastructure).
  - NO automatic status changes and NO automatic billing-month moves —
    the guard makes humans act; the existing manual override surfaces
    (billing-month override, workflow override with reason) remain the
    only mutation paths. (Addendum B rules untouched.)

### D.11.3 Acceptance tests (extend `test_sprint179a_work_plan.py`)

1. Slot planned last Tuesday, still ASSIGNED → appears today with
   "N dagen te laat"; disappears from today (stays in its home week)
   once completed or rescheduled.
2. Slot UNABLE_TO_COMPLETE → appears in the follow-up list with age;
   leaves it only via reschedule / reassign / cancel.
3. Job with future due date shows "over N dagen"; day count steps
   correctly across week boundaries; a slot chip never uses the word
   deadline.
4. EW deadline inside the open billing month, ticket in
   WAITING_FOR_MANAGER for 7+ days → appears in the at-risk list with
   stage "wacht op controle" and age; disappears when confirmed.
5. Ticket planned in month M, completed and confirmed in month M+1 →
   at-risk list showed it during M; billing month follows the existing
   Addendum B completion-month rule (no auto-move).

---

## Appendix A — CLAUDE.md patch (add as a new section after "Frontend conventions")

```markdown
### Frontend redesign rules (Addendum D)

- The frontend redesign source of truth is
  [docs/product/sot-addendum-d-frontend-redesign.md](docs/product/sot-addendum-d-frontend-redesign.md).
  For presentation, vocabulary, navigation, and flow shape it WINS over
  older UI descriptions in the base SoT (§16) and over current code.
- **Vocabulary is law:** one name per concept (Addendum D §D.2). Never
  introduce a new user-facing work noun; the §D.2 banned list applies to
  all UI copy, both locales, in lockstep.
- **Every FE sprint self-verifies visually** per Addendum D §D.10: run
  the stack, screenshot the changed surfaces per affected role, check
  against the sprint checklist, at most TWO fix iterations per item,
  then report. Screenshots are design evidence; measured geometry
  remains the standard for layout-regression claims.
- Detail pages: fact block first, ONE primary action from
  `actions.can_*`, corrections behind "Geavanceerd" with their existing
  warning/audit surfaces. No new frontend business inference — if a
  display needs a derived state, request/extend a backend-computed field
  (the `display_phase` pattern), never compute it client-side.
```

## Appendix B — docs/README.md index row (add in the same commit)

```markdown
| [product/sot-addendum-d-frontend-redesign.md](product/sot-addendum-d-frontend-redesign.md) | **Addendum D** (2026-08-28): the frontend redesign — diagnosis, vocabulary table, role-based navigation, the meerwerk `display_phase` presentation model, the five core flow shapes, UX principles, screen-inventory verdicts, the FE sprint plan, and the bounded visual-verification protocol. **Wins over base SoT §16 for the items it covers once signed off.** | Whenever a redesign decision is made or a FE sprint completes. |
```

---

## D.12 Owner feedback, round 1 (2026-08-29)

The owner's first live review of crmtest (FE-1..FE-3 deployed). The
owner's words are the spec; where they conflict with earlier text in
this Addendum, the owner wins. Implemented as sprint **FE-4**.

1. **Back goes where you came from.** A detail page's "back" returns to
   the in-app surface the reader actually came from — My Schedule with
   its week and filters, Mijn meldingen, Tickets with its query intact.
   Role default when there is no in-app origin: staff / building manager
   → My Schedule, customer → Mijn meldingen, provider admin → Tickets.
   The legacy tickets list is not a customer surface: a customer role
   reaching it is redirected to Mijn meldingen (single-ticket deep links
   keep working).
2. **Honest date words, cards and details alike.** "Gepland / Planned
   <date>" ONLY when a planned date exists. An unplanned item says
   "Aangemaakt <date>" + "nog niet ingepland". A customer's wished date
   is a wish, never a plan. The creation date is never dressed as a plan.
3. **One headline lateness per item.** The deadline when one exists,
   otherwise the planned day; the card's number and the detail's number
   come from the same server field (`days_until_due` / `due_kind`).
   Every other time-fact is secondary and says what it is ("87 dagen
   zonder uren" is information under the facts, never a second "te
   laat" headline). One alarm per item, maximum.
4. **Closed and settled items stop applying pressure.** Past tense,
   neutral styling — "Afgerond op <date>" and, when after the deadline,
   "(2 dagen na deadline)" as quiet history. No red chip, nothing that
   implies action. Work waiting on the customer wears a "wacht op klant"
   chip on provider boards, never late-styling against the provider.
5. **My Schedule reading order (current week):** today's planned open
   work first; carried late open work second, with its honest origin;
   settled work visually settled at the end of its day; "Nog niet
   gepland" collapsed to a count-with-age button that opens the drawer,
   oldest first. The stat tiles reduce to what earns its place (Totaal /
   Te laat / Open); the rest fold into the filter.
6. **Multiple custom meerwerk lines.** "Iets anders" is a real cart line:
   add another, each rendered like a priced line (title, optional note,
   "prijs volgt"), all listed on the confirm page. The customer list
   filters by phase.
7. **Multi-customer membership stays as is** (no model change); the
   customer chooser appears only for a multi-membership user, never for
   a single-membership one.
8. **Turkish locale is parked until after FE-7.**
9. **Language integrity:** no hardcoded Dutch may reach an English
   session; the language switch is plainly visible for every role; the
   SA and provider-admin demo accounts review in English.


---

## D.13 Notification localization — decision memo (FE-7, 2026-08-29)

Written, not built (FE-7 closes the redesign plan; this is the one item
it hands to the owner as a decision). Facts below are from the code on
`feat/fe-7-final-audit`; nothing in this section changes behaviour.

### D.13.1 Where we stand

- **Every notification is composed as finished text and stored as
  text.** `NotificationLog` (email audit) holds `subject` + `body`;
  `Notification` (the bell feed) holds a `summary` string. Neither row
  carries a template key, a parameter payload or a language column
  (`backend/notifications/models.py`).
- **One chokepoint, ten composers.** `send_logged_email(recipient,
  subject, body)` (`notifications/services.py:775`) is the only email
  door, but it receives strings already rendered by ten call sites
  (ticket created / status changed / assigned / unassigned / slot
  unable, password reset, invitation, invoice sent, the monthly invoice
  run, and the WP-1 billing-month digest that reuses
  `INVOICE_RUN_COMPLETED` and deduplicates on
  `subject__startswith`). About eighteen more sites write the bell
  `summary`.
- **Language is hardcoded per site, not resolved per recipient.** The
  ten email composers and the SLA L1 warnings write Dutch; the deadline
  reminder, the staff part-assignment and the extra-work lifecycle bell
  lines write English. Exactly one pipeline, the W-LATE escalation
  ladder (`tickets/escalations.py`), resolves `user.language` per
  recipient — by hand, with a dict of the two languages, not with
  gettext.
- **Django i18n is on but empty.** `USE_I18N = True`, `LANGUAGE_CODE =
  "nl"`, two `LANGUAGES`, no `LOCALE_PATHS`, no `locale/` directory, no
  `.po` files, zero `gettext` calls, zero templates. The
  `UserLanguageMiddleware` activates the user's language, but it runs
  before JWT authentication and is a no-op for `/api/`; Celery tasks
  have no request at all. No notification is emitted under an active
  per-user locale today.
- **The frontend is a hybrid.** The bell renders a translated title from
  `event_type` for the SLA kinds (`t("notifications.sla.<kind>")`) and
  prints the stored `summary` verbatim underneath; non-SLA rows show
  only the stored text. `sla/warnings.py` deliberately keeps its
  summary to facts (numbers, names, dates) because "a server-side Dutch
  string in a translated interface is a string nobody can translate".
- **Copy is pinned by tests.** Fifteen backend tests assert literal
  subject/body fragments ("Status gewijzigd", "Wacht op beheerder",
  "facturatiedatum"); the escalation tests assert both languages; one
  test pins the backend's status-label mirror byte-for-byte to
  `frontend/src/i18n/nl/common.json`.
- **The user's language exists and is already respected by the UI.**
  `User.language` (`nl` default, `en`), written from the user menu,
  read by `useLanguageSync`. The precedent for server-side per-reader
  resolution is `TicketCategory.label_for(language)` (dual
  `label_nl` / `label_en` columns, one resolved `label` in the API).

### D.13.2 The two options

**Option A — store keys + params, render per reader.** A notification
row stores `template_key` + a JSON `params` payload (ticket number,
names, dates, amounts) and no text. Email renders at send time in the
recipient's language; the bell feed renders at read time in the
viewer's language (the API resolves it, the SPA never composes copy
from parts — SoT §11.1 holds). Changing the wording of a notification
later re-renders history; a user who switches language sees their old
bell rows switch too.

- Cost: additive migration (`template_key`, `params` JSON, keep
  `subject`/`body`/`summary` as the rendered cache); a small backend
  catalogue of ~25 kinds × 2 languages; every one of the ~28 composer
  sites rewired to emit `(key, params)` instead of text; the bell
  serializer resolves per viewer; the fifteen copy tests move to the
  catalogue; the digest's `subject__startswith` dedupe becomes a
  key-based dedupe. Roughly one backend sprint plus a small frontend
  one (the bell drops its client-side SLA title map).
- Risk: params must be stable across re-renders (store names, not ids
  that may be deleted); the rendered cache must still be written for
  the NotificationLog audit rows (what was actually sent, verbatim, in
  the language it was sent in).

**Option B — resolve the language at creation, store rendered text.**
Keep the tables as they are. Each composer site resolves
`recipient.language` and renders once, in that language, as the
escalation ladder already does; the stored text is what the reader
sees, forever. The bell stays "print what is stored".

- Cost: the same ~28 composer sites each gain a language switch (a
  `dict[lang]` or a gettext catalogue — with gettext, add
  `LOCALE_PATHS`, a `locale/` tree and `translation.override(lang)`
  around each render); the fifteen copy tests double to cover EN; no
  migration; the bell's client-side SLA title map becomes redundant
  and is removed. Roughly half a backend sprint.
- Risk: history is frozen in the language the recipient had at the
  time (acceptable for email — that is the audit record — and mildly
  odd for the bell after a language switch); a copy fix does not
  reach rows already written; multi-recipient events render the
  same body N times (cheap).

### D.13.3 Recommendation

**Option B for email, Option A's read-time resolution for the bell —
but built as ONE mechanism: a keyed catalogue rendered server-side.**
Concretely: introduce the catalogue (`notifications/copy.py`, keyed,
two languages, one `render(key, params, lang)`), make every composer
site call it with the recipient's language (email: rendered once at
send and stored, exactly as today's rows are — the audit record stays
verbatim), and store `template_key` + `params` on `Notification` only
(additive, nullable) so the bell endpoint can re-render per viewer
while old rows keep their stored `summary`. This gets the customer's
inbox and the customer's bell into their own language in one sprint,
keeps NotificationLog honest, and leaves the door open to full Option
A later without a second rewrite. Migration cost: one additive
migration on `Notification`, no data backfill (old rows render from
`summary`), the composer rewiring above, and the copy tests moved to
the catalogue.

What it does not do, and should be said out loud: Turkish stays
parked (§D.12.8) — the catalogue makes adding a third language a copy
task, not a code task, which is the point.

**Owner decision required:** A, B, or the hybrid above; and whether the
customer-facing emails should carry the provider's brand voice per
company (they do not today; every company sends the same Dutch text).
Until decided, nothing changes: new notification copy keeps following
the existing per-site language (Dutch for email, Dutch or English for
the bell as the site dictates), and every new composer must at least
route through `send_logged_email` so the eventual rewiring has one
door to find.

---

## D.14 Honest dates on real data — the P-1 rulings (2026-08-29)

The owner reported the "Planned" bug (§D.12 item 2) a SECOND time after
FE-4 shipped. FE-4's fix passed on fixtures whose planned dates were all
real; on crmtest, TCK-2026-000209 ("ggtg", created 3 June, never
planned) still read "Planned 3 Jun — 87 days late". The rulings below
are permanent and win over any older text.

1. **A date is a plan only if a person made it.** `scheduled_start_at`
   is read as a plan only behind a schedule annotation row (a person
   scheduled it), a recurring occurrence (the plan-of-record), or the
   extra work's `provider_planned_date` (the provider's commitment).
   A date in the column with none of those behind it is a PHANTOM: the
   Sprint 9B spawn seed copied the cart's `requested_date` — which the
   create serializer defaults to the day of entry — into the schedule
   column of 43 of crmtest's 54 extra-work tickets. The seed is stopped
   (a spawned ticket is born UNPLANNED); the existing rows stay in the
   database and are handled by presentation. Backend:
   `tickets/plan_provenance.py`, read by `tickets/job_dates.py` so the
   board, the ladder, the counts and the detail all stop at the same
   fact. Additive read-only fields: `has_real_plan`, `plan_source`,
   `planned_by_name`, `planned_at`, `created_by_name` on the ticket
   detail, the extra-work detail and every work-plan entry.
2. **The words.** Real plan: "Ingepland voor <date> — door <name>, op
   <date>". No real plan: "Aangemaakt op <date> door <name> — nog niet
   ingepland · al N dagen" — never "te laat" against a plan that does
   not exist, never the word gepland. Deadline lateness keeps its own
   words (§D.11 G3). EVERY ticket and meerwerk detail states
   "Aangemaakt op … door …" as a plain fact; nobody guesses who opened
   a ticket. The card and the detail print the same numbers (FE-4's
   rule), now tested against a phantom-planned fixture
   (`tickets/tests/test_p1_honest_dates.py`).
3. **Work waiting for a manager does not rot in the past.** A ticket in
   WAITING_MANAGER_REVIEW is neither pending nor over, and the board
   read "not pending" as "settled": the card sat calm on the day the
   worker finished and slid into last week while the billing chain
   (§D.11 G4) stayed broken at the manager. Rule 8 of
   `tickets/work_plan.py`: in the current week such a job hangs on
   today's column of the MANAGER's board (`placement: REVIEW`,
   "Wacht op controle — al N dagen", `stuck_age_days` from
   `manager_review_at`), not settled, not late, until it is confirmed.
   Past and future weeks keep rule 1. A worker's own completed slot is
   unchanged: it stays settled on its own day.
4. **Method.** §D.10 verification walks the OLDEST real records on
   crmtest (read-only), not only fixtures; every sprint report leads
   with what the ugly data showed (CLAUDE.md, Frontend redesign
   rules). The owner's three named tickets were P-1's acceptance test.


## D.15 Schedule truth and contracts clarity — the P-3 rulings (2026-08-29)

The owner — the system's own designer — needed three days to understand
why tickets waiting on the customer sat in past day columns of the
working week. That is the bar failing: design must teach, paragraphs do
not. P-3 is the schedule truth pass that follows, plus a words-and-layout
pass over contracts. The rulings below are permanent and win over any
older text.

1. **Work waiting on the customer is not in a day column.** Rule 9 of
   `tickets/work_plan.py` (predicate in `views_work_plan.py`,
   `_ticket_waiting_customer_q` and its slot twin): in the CURRENT week a
   ticket in WAITING_CUSTOMER_APPROVAL is in no column. It is one row
   behind its own chip — "Wacht op klant: N" / "Waiting for customer: N"
   — in its own calm blue, distinct from settled grey, review amber and
   late red, opening the same drawer as "Nog niet gepland"
   (`waiting_customer_entries`, `counts.waiting_customer`, whole scope).
   Past and future weeks keep placement as history.
2. **One card, one voice.** A work-plan card carries exactly ONE status
   line (the settled sentence, or the reason it is a visitor on this
   column, or — at home and live — the plain status badge) and AT MOST
   ONE time chip (a real clock, else "Gepland na de deadline", else the
   deadline countdown, else the day window). The couldn't-complete
   reason is never on a card or a list row: the card says "Niet gelukt
   op 26 aug", the reason lives on the detail. Every closed shape has
   its own words (rejected, converted, cancelled, taken off the job) —
   the app's existing phase and slot vocabulary, never a second set.
3. **A clock renders only when a real time exists, and the SERVER
   decides.** A date-only plan is stored as local midnight; the browser
   used to print that instant in its own zone, which is where "01:00 AM"
   came from (`2026-08-26 22:00Z` read three hours east of Greenwich).
   Every work-plan entry now carries `start_time` / `end_time` and the
   ticket detail `scheduled_start_time` / `scheduled_end_time` plus the
   day (`scheduled_start_day`), all in `TIME_ZONE`; a card and the
   schedule card print a clock from those and never from the raw
   instant. Writers send a plan as a NAIVE local datetime
   (`lib/isoWeek.ts::plannedDayIso`), which DRF reads in the server's
   zone: the day picked is the day stored whatever zone the browser is
   in, and "plan for today" / "reschedule" no longer hand a job a 12:00
   clock nobody chose.
4. **The manager sees the truth.** WAITING_MANAGER_REVIEW has a
   provider-facing phase of its own, `WAITING_MANAGER_CHECK` — "Gemeld
   als klaar — wacht op uw controle" / "Reported done — waiting for your
   check" — on the banner and on the card; the customer keeps "wordt
   uitgevoerd" for the same status through the existing per-viewer
   mechanism (`tickets/display_phase.py`).
5. **Plan-after-deadline warns, never blocks.** The schedule dialog says
   in plain words when the chosen day passes the deadline; the card and
   the detail state "Gepland na de deadline" (`planned_after_deadline`,
   computed once for both from a REAL plan against a REAL deadline).
6. **The numbers reconcile, and the matrix is complete.**
   `tickets/tests/test_p3_schedule_truth.py` asserts that every count on
   the payload equals the list it describes (total = open + in progress
   + done + blocked = the cards on the board; late = its three rungs;
   undated, overdue, upcoming, stuck and waiting each equal their list;
   nothing is in two places), and places every TicketStatus, every slot
   status and every extra-work status on a pinned Wednesday. The
   remaining "by design" holes are recorded in the P-3 sprint report.
7. **No inner scrollbars on the board.** A day column grows with its
   load and folds past six cards behind "Toon er nog N"; the 420px cap
   with an inner scrollbar is gone. The sidebar keeps its scroll position
   across route changes.
8. **Contracts: words, layout and self-teaching modals only.** A
   contract, wherever listed, reads as a sentence ("B Amsterdam — € 850
   per maand voor B1 + B2 — sinds jan 2026 — volgende periode: sep");
   every term teaches on click by SHOWING it with that contract's own
   numbers ("Versie 2 — geldig vanaf 1 sep — wat veranderde: € 800 →
   € 850 per maand"); an unset fact is absent, never a dash. **The
   contracts functional revision awaits the owner's meeting
   (2026-08-30); until then no rule, field, calculation or endpoint
   changes.** The contracts model was carried over from the reference
   system and its rules are not P-3's to touch.
9. **One teaching line per surface.** Any surface with more than one
   short teaching line is cut to one — including P-2's invoices sentence
   — and structure carries the rest.


## D.16 The joy pass — the P-4 rulings (2026-08-30)

The owner walked the plan flow and got stressed, lost, and blocked by
an invisible error. The law of this sprint, in the owner's words:
imagine you work at this company and know NOTHING about computers or
this system, and you try to do a job. If the system lets you finish
WITHOUT knowing it beforehand, that surface passes — as ticket
creation and the meerwerk create page do. Every create/edit surface,
every modal and (extended mid-sprint) EVERY PAGE is measured against
this. The rulings below are permanent and win over any older text.

1. **Units everywhere they are true.** A service is priced per hour,
   per m², per item, as a fixed price, or per the operator's own unit;
   the meerwerk cart says so on the chip ("per uur"), as the suffix of
   the quantity box ("50 m²"), on the cart line and on the confirm
   page — from EXISTING `unit_type` data only (`Service.unit_type` read
   onto the customer price row as `service_unit_type` /
   `service_unit_label`; `lib/unitLabel.ts`). An "iets anders" line is a
   REQUEST FOR WORK: its placeholder and helper say that quantity and
   unit belong in the text ("bijv. 2x ramen wassen, ±40 m²"). A
   persisted unit on a custom line needs a migration and is ledgered,
   not built. "On several days" is one plain sentence ("You are
   creating one meerwerk per chosen day — N days = N meerwerken"), a
   calm day picker, the chosen days as chips, and a result that names
   the days ("Created — one for each chosen day"). No mirror/copy
   jargon exists in either locale.
2. **The plan modal is a guided staged flow** (`PlanWorkDialog`), the
   create page's pattern: (1) WHEN — "First work day" / "Last work
   day", the customer strip in plain words ("Customer would like: Sep
   4 · Must be done by: Sep 3"), a day past the deadline warning INLINE
   at the field the moment it happens, never blocking; (2) WHO AND HOW
   MUCH — people, then per person the plan's days as chips with an
   hours box per chosen day, a "no day yet" box, a per-person total and
   a grand total, the hours budget optional under the total; (3) DONE
   MEANS — the two completion switches, one line each. Any day
   combination (2+3, 1+3, a single day) reads exactly as chosen.
3. **A number counts only if it is on screen.** The double-count the
   owner hit (4 in the no-day box, 4 on a day, total 12) was a day that
   had dropped out of the window: the old grid kept its hours in state,
   in the total and in the payload. Now un-choosing a day deletes its
   hours visibly; hours kept from an earlier plan on days outside
   first..last work day are shown as "outside the plan" chips and
   counted only while shown; and the SERVER refuses a new or changed
   dated row outside the committed window
   (`planning.ERR_PLANNED_HOURS_OUTSIDE_WINDOW`, `field` and `days` in
   the body; unchanged rows pass so "people's days stayed on the old
   dates" stays expressible) — `extra_work/tests/test_p4_plan_days.py`.
4. **Moving a plan asks in plain words.** When the first work day moves
   and people already have days: "Also move everyone's planned days
   along?" — yes shifts every dated row by the same difference inside
   the same save (the payload replaces the distribution; no new
   endpoint); no keeps them and says "People's days stayed on the old
   dates — adjust them below" and shows them. A worker's plan row
   shows the DAY only unless a person chose a time (§D.15 rule 3).
   Past days stay unplannable; worked hours for past days stay
   enterable through the recorded unlock.
5. **Errors live where the person is.** Field-level messages at the
   field, a one-line summary next to Save, the first error scrolled
   into view. The server's body is read for its shape
   (`lib/apiFieldErrors.ts`: `code`, `field`, `days`, DRF per-field
   entries) and mapped to the form's own sentences; the generic "That
   was not accepted" may appear only when the server truly gave no
   field detail. This is the pattern for every converted form.
6. **Money calms.** Addendum B unchanged; the tab states consequences.
   Under the billing month: "This work bills in December: it will
   appear as unbilled work on B Amsterdam's December invoice on the
   Invoices page. Nothing is sent automatically." After "Save hours to
   bill": "€424 saved. You will find it under Invoices → B Amsterdam →
   December, as unbilled work." (`lib/billingSentence.ts`, one
   destination sentence for both surfaces.) Hours → "Close week" says
   what closing means, who can still change what, and that it can be
   reopened; "Weighted" reads "Hours × factor" with a click-to-teach.
7. **Navigation tells the truth.** A ticket of kind MEERWERK lights
   "Extra work" in the sidebar, not "Tickets" (the unified queue keeps
   it with the pill — base SoT §1.4 stands; only the active state
   lied). `lib/currentTicketKind.ts`: the detail page publishes the
   kind it loaded, the shell subscribes. My Schedule's first paint is
   honest: while the week is loading it says so and claims nothing
   empty — the "missing chip until a second click" was the response in
   flight behind seven "Nothing planned" columns (probed on crmtest).
   The sidebar records its scroll position unconditionally at click
   time (the `> 0` guard restored a stale deep position).
8. **The waiting-for-customer drawer acts.** Each drawer row carries
   `can_override_customer_decision` — the SAME rule as the ticket
   detail's Advanced fold, moved to `tickets/override_authority.py` and
   asked by both; nothing is widened (SA; CA in the ticket's company;
   BM assigned with the B6 key; only at the decision step). One amber
   "Approve on customer's behalf" button runs the EXISTING override
   flow: required reason, `is_override`, the audit row. The ticket
   lands settled on its day column (`tickets/tests/test_p4_waiting_drawer.py`).
9. **The modal law, and the page law.** Every create/edit modal and
   every page is either converted to the guided pattern (staged
   sections, plain labels, one primary, field-level errors, a
   consequence sentence where money or scheduling results) or appears
   in the P-4 report's inventory table as "passes as is" / "decision
   needed (why)" / "queued". The approved references: ticket create,
   the melding flow, the meerwerk create page, the ticket detail, the
   meerwerk detail, My Schedule, the Permissions page, and — added by
   the audit — the SLA warnings page (plain sentences, working-day math
   explained, every warning naming who receives it: steal its sentence
   style wherever numbers need explaining). Nothing is silently
   skipped; the owner never reports a page twice: if it is in the
   table, it is owed. Converted in P-4: the New/Edit contract modal
   (four stages, field errors, the billing consequence in the form's
   own numbers — rules frozen, §D.15), the Contracts page (five filters
   behind one Filter button with chips, one view hierarchy), Company
   detail (fact block, the policy as the read-only twin of the edit
   page's toggle card, SLUG behind Advanced, folds, and it can never
   render silent white: an explicit "cannot be shown" state plus a
   per-route error boundary in the shell), Company edit (the duplicated
   read tables cut), Building detail (facts, no dash tiles, empty
   fields hidden, cost split behind Advanced with a calm sentence,
   valueless columns dropped), the customer Contracts tab (a draft
   reads as one; the register bounded, € 0.00 rows collapsed, a search
   box), Settings (a horizontal profile header at every width),
   Services & catalogs and People (one top-level tab component — the
   customer page's row — with subordinate second-level pills; "Lijst /
   Categorieën / Eenheden"; "Catalogus van: …"), and the pill families
   unified so chip text sits centred.
10. **Decisions the owner holds** (from the inventory): where the extra
    work register lives (Contracts tab vs Invoices/Work — web-Claude
    recommends nearer Invoices); whether `ConfirmDialog`'s disabled
    destructive styling stays; what the hour-type multiplier drives
    (pay, price, both); the settings page's three independent saves.

## D.17 The closer — the P-5 rulings (2026-08-30)

The owner's live walkthrough of P-4 on crmtest, and web-Claude's
session notes, closed by P-5 (`feat/p5-closer`). Decisions recorded:

1. **The error-body law.** A server refusal ALWAYS names its reason in
   the body — a `detail` sentence, or a per-field message — and the
   screen shows THAT in its own words (`lib/transitionRefusal.ts`, one
   i18n sentence per stable code). The generic "That was not accepted"
   is for a truly detail-less 5xx or a network failure and nothing
   else. The requirements refusal lists its `unmet` keys; the
   requirements endpoint reports `actual_hours` so the modal points at
   the Money tab before the press (`tickets/tests/
   test_p5_transition_refusals.py`). A requirement is a calm notice,
   never a red alert.
2. **One plan, one date, one world.** The ticket's window and the
   meerwerk's committed window are ONE fact seen from two ends:
   `job_start_day` / `job_end_day` on the detail (own plan, else the
   meerwerk plan); a plan written on the meerwerk pushes first AND last
   day onto the ticket; a start set on the ticket mirrors onto the
   meerwerk (`tickets/schedule.py::mirror_window_onto_extra_work`).
   The transition modal asks for a DAY with an optional clock, never
   the moment of the press. The schedule card tells one story; the
   "committed" row renders only when this job holds a different date
   of its own, and says so. Meerwerk surfaces never say "ticket":
   i18next `context: "meerwerk"` variants, the TCK number behind
   Geavanceerd.
3. **The missing-piece pointer** (`lib/missingPiece.ts`): a sentence
   that says "X is missing" carries a door that lands ON X — the tab or
   modal opens, the part scrolls into view and lights up, and it says
   what it needs. Used by the hours gate (Money tab), the pricing gate
   (each missing piece opens the plan modal on that piece) and the
   "open the split" link (building detail `?piece=cost-share`).
4. **The connections layer** (S7): every detail page names the records
   it feeds and is fed by, as links with one line of context —
   contract → buildings with their split, visits, invoice trail;
   building → contracts covering it, the split says WHERE it acts;
   occurrence ticket → its recurring job and contract, which visit of
   the year; invoice → its contract period, each line's meerwerk and
   building. Additive read-only fields, detail responses only, no new
   nav, no new models.
5. **SLA warnings, the owner's additions** (S8): who else receives
   each warning (rings + an extra address), a third escalation step
   (off by default), weekend handling (working hours or the clock, per
   company; warning 3 always counts calendar days), and a weekly
   Monday list for the admins. The redesign's first migration —
   `sla/0002` (11 additive columns, defaults = today's behaviour) and
   `notifications/0021` (a choices-only `AlterField`, no SQL).
6. **Decisions recorded:** the custom-line unit stays TEXT
   (dropdown/migration cancelled — owner tested and approved); the
   deadline hard-block is parked as a possible future company policy;
   SLA customisation is UN-parked and built as S8 (owner decision
   2026-08-30); register placement still awaits Ramazan; the contact
   row's free-text role label ("A") is no longer rendered on read-only
   lines — the system cannot say what it means, and it stays editable
   on the Contacts page.
7. **Verification rule** (CLAUDE.md): replays create their own
   fixtures and list every data mutation at the top of the report.


---

## D.18 The visible round — the P-6 rulings (2026-08-30)

The owner walked P-5 and said "it doesn't seem a lot changed" — correct:
P-5 fixed the journey's spine and queued the visible page sets. P-6 is
those pages (`feat/p6-visible`). Rulings recorded:

1. **The invoices pages are the bone** (V1). `/invoices` reads top to
   bottom as one story: four facts (due now · drafts · issued-not-sent
   · at risk), the due rows with ONE primary per row (a row with
   nothing to generate carries its reason in words, not two dead
   buttons — rules 3 and 14), the billing-month guard folded with its
   count, and every invoice grouped by billing month with the month's
   count and total on its heading, status tiles with real counts, a
   search box and a filter fold. `?customer=<id>&period=YYYY-MM` opens
   the page on that customer and month, and the "€X saved — Invoices →
   customer → month" toast (`lib/billingSentence.ts::invoicesDestination`)
   is a door that lands there. `/invoices/:id` opens on one strip that
   says where the invoice stands and what happens next, with the one
   primary action beside it (Issue / Send / Download), four facts
   (customer · period + contract · amount · dates as words when unset,
   rule 15), the lines with their meerwerk and building links, the
   text-on-the-invoice fold, the document, and every correction
   (delete draft, back to draft, credit note) under Geavanceerd.
2. **Recurring work carries the ticket detail's rhythm** (V2): a
   header without buttons, the rule sentence with the next visit in it
   on the phase strip beside the one primary action (Edit; Restore
   when archived), four facts (where · what · when · who — a crew that
   is not set says so in words), the visit calendar, the money in a
   titled card, and Plan-further-ahead / Archive under Geavanceerd.
   The list's "Time window" column becomes "Visits per day" and a job
   with no clock says "time not set" (rule 15).
3. **Vocabulary ruling.** §D.2 offers "geplande beurt (or 'bezoek')".
   The code had already standardised on **bezoek / visit** everywhere
   the ticket side speaks ("bezoek 3 van 12 dit jaar"); switching the
   recurring pages to "beurt" would have created two names for one
   thing. P-6 keeps *bezoek* as the one word and removes the last
   "tijdvenster / venster" leftovers (list column, facts, calendar
   default, override dialog). The owner may still overrule to
   "beurt" — it is a bundle-only change.
4. **Global search** (V4.1): ONE read-only endpoint, `GET
   /api/search/?q=`, viewer-scoped by the EXISTING scope helpers
   (`scope_tickets_for`, `scope_extra_work_for`, `scope_customers_for`,
   `scope_buildings_for`, `manageable_user_ids_for`), five groups of at
   most five with a `truncated` flag; nothing fuzzy (`icontains` on
   number/title/name). The header box shows a row as a link only where
   the viewer may go, using the same predicates as the sidebar
   (`canAccessExtraWork` keeps the meerwerk door shut for STAFF).
5. **Top-5 attention** (V4.2): the dashboard's attention list orders
   its rows by the order of CONSEQUENCE, shows five, and offers "show
   all N". The order: review (finished work waits on your check) →
   approval overdue (the customer went silent on finished work) → at
   risk (will miss the billing month) → stuck (planned, never done) →
   awaiting price → unassigned → unplanned → awaiting the customer's
   decision. Counts do not decide the order; a row with a zero count
   does not render.
6. **Stale-work triage** (V4.3): in the "Not planned yet" drawer,
   select rows and park or close them with ONE reason. `POST
   /api/tickets/bulk-triage/` walks the machine's OWN legs (OPEN →
   ACKNOWLEDGED → ON_HOLD; APPROVED → CLOSED) through
   `apply_transition`, so every leg writes its history row with the
   reason; closing from any other status is the out-of-machine jump
   only a SUPER_ADMIN may make, recorded as an override
   (`is_override` + `override_reason`) — the Close action is offered
   to that role only (rule 14). A meerwerk has no parked state: park
   skips it and says so; close cancels it through its own transition
   with the same reason. Per-item results, never an aborted batch
   (`tickets/tests/test_p6_bulk_triage.py`). A parked ticket STAYS in
   the "Not planned yet" lane — the §D.15 schedule-truth matrix places
   ON_HOLD there on purpose (`test_p3_schedule_truth.py`) — and the
   row now says "Parked"; whether parked work should leave the lane is
   a decision the owner holds (checklist NEXT).
7. **Money leaves the API with two decimals** (V5.3): `period_amount`
   (`buildings/serializers.py`) is quantised to cents before it
   becomes text; the contract serializer's `monthly_amount` /
   `yearly_amount` / `total_hours` and the active revision's `amount`
   / `hours` are two-decimal STRINGS (the shape the frontend types
   declared, and a `SerializerMethodField`'s raw Decimal was leaving
   as a JSON number that dropped its scale). The contracts page's
   local `formatMoney` always renders two decimals.
8. **The money card says its waiting state once** (V5.1): the value
   slot carries "Wacht op gewerkte uren" instead of a short word beside
   the long one.


## D.19 The finishing round — the P-7 rulings (2026-08-30)

The owner's last list before "the system is done" (`feat/p7-finish`).
Every item was merge-blocking. Rulings recorded:

1. **One count in the Enter-hours modal, and it says what a row is.**
   The setup banner counted (person, building) pairs; the grid counted
   rows — a pair × hour type × job, reconciled with what is already
   saved — so "4 rows" sat above a grid saying "6 rows". The banner
   now states only that building access was checked; the grid's count
   is THE count, and its caption defines a row ("one person at one
   building on one job, per hour type"). Dutch uses ONE word for it,
   *regel* (the setup said *rij*). The save math was verified
   server-side (`timesheets/tests/test_p7_mixed_week.py`): three rows
   for one person at one building are three facts and stay three
   entries; "0" deletes; untouched cells are not sent; the multiplier
   is snapshotted per entry; one bad cell writes nothing for anybody.
   Nothing was broken — every finding is by design.
2. **Silent loss dies.** Switching week over unsaved hours ASKS first
   (the My-hours pattern, now in the modal too); the standing
   "unsaved hours are cleared when you switch week" sentence is gone
   because the loss it described no longer happens.
3. **The fill row is a tool.** Its own tint and edge, an icon, a verb
   ("Fill every standard row at once") and one caption — nothing about
   it reads as a person's row.
4. **One person, several parts.** The name prints once; each further
   block of theirs is a PART that says what it is: "on Ticket #374",
   "on Extra werk regie uren +1", "general hours, not linked to a
   job". Job labels wrap instead of clipping at 18 characters.
5. **Removal after Add — root cause.** The Extra Work page never passed
   the plan dialog a remove handler, and the dialog renders its X only
   when one exists; the ticket page passed one and removed silently.
   Now: every X asks once ("X leaves the job. Planned hours from today
   on are cleared; worked hours and the past stay.") and runs the
   EXISTING unassign. The EW-side door (`bulk-assign` with
   `mode: "unassign"`) now clears the person's open plan like the
   ticket-side doors do (`extra_work/tests/test_p7_plan_removal.py`).
6. **Last-before-first is refused at the field, the moment it happens;
   the plan modal reveals one stage at a time** — dates; the people
   and hours once a first day exists; "done means" once someone is on
   the crew. A stage never hides again; a caller pointing at a missing
   piece opens it.
7. **Approving on the customer's behalf is AMBER** — on the agenda row
   and in the meerwerk's Geavanceerd fold — and its reason dialog wears
   the same amber band. P-5 made it a button and dropped the colour in
   passing; the exceptional act must look like one. The one amber
   button (`btn-warning`), never red.
8. **A billing month is words, everywhere.** "oktober 2026", never
   "2026-10" nor "10-2026": the meerwerk's billing line, its save
   toast, the invoices page's due sentences, generate panel and filter
   chips, the invoice detail's period, the customer's invoice pages.
   The consequence sentence is the owner's: "Dit werk wordt gefactureerd
   in oktober 2026 — het verschijnt op de factuur van B Amsterdam voor
   oktober 2026."
9. **A committing button states its consequence in one line before
   it acts**: "Save hours to bill" (readies the amount for that
   customer's invoice for that month; nothing is sent), "Close week"
   (locks everyone's hours; reports and invoices calculate from them).
   Generate and Send/Issue already carried theirs.
10. **The contract modal reveals one stage at a time** — who and
    where; when (once a customer and locations are chosen); billing
    (once a start date exists); notes. Editing opens all four. Rules
    stay frozen (§D.15 item 8). **The contracts page has ONE view
    control** (list / by customer / by location); the measure (prices
    / hours) and the timeframe (per month / per year) are two selects
    in the Filter fold with chips when off their default. P-4's
    "tiered" bar named CSS classes that never existed.
11. **The SLA page is calm again.** The default view is the warnings
    and their values; the recipients, the extra address and the third
    step fold behind ONE "Aanpassen" per warning whose summary says
    what is set ("also to the responsible manager · third step after 3
    days" / "standard"); the weekend rule and the weekly summary fold
    the same way on the counting card. Every P-5 S8 feature stays.
12. **Settings is a horizontal header** at every width: avatar, name,
    email and role on one line, the facts (member since, last sign-in,
    access) as an inline row, the photo control at the right; the
    forms take the full width below. The P-6 inventory's "converted"
    rows were spot-checked against live crmtest (the audit table is in
    the P-7 report).
13. **Parked work leaves the nag.** ON_HOLD-without-a-day is no longer
    in "Not planned yet" (`counts.undated`, `undated_entries`); it is
    its own quiet list, `parked_entries` / `counts.parked`, behind the
    same drawer as "Geparkeerd (N)", each row with the reason it was
    parked for (the note on its ON_HOLD history leg). A parked job
    WITH a day keeps its board placement. The §D.15 matrix row for
    ON_HOLD reads `("rolled", "planned_fri", "parked")`
    (`tickets/tests/test_p3_schedule_truth.py`,
    `tickets/tests/test_p7_parked.py`). This closes the decision P-6
    left with the owner.
14. **Small closures.** The recurring calendar's inline styles became
    classes, the legend derives from the same tick list the cells
    paint with, and skipped (grey, dashed) and cancelled (red-tinted,
    struck) no longer share one dot; the pricing page's six secondary
    panels share one shell and the bulk-raise panel is staged (which
    prices → how much, from when); the truncated job chip in the hours
    grid wraps to its full label.

## D.20 The truth round — the P-8R rulings (2026-08-30)

The owner's standard, now in CLAUDE.md §1: the owner is not the first
QA tester. Web-Claude audits every deploy before the owner walks; a
correct HTTP status is not a correct product — the screen must say
the truth where the user clicked, and after every transition the work
must be FINDABLE through normal navigation. P-8R (`feat/p8-truth`)
fixed the audit's findings and walked the whole Extra Work matrix on
crmtest with its own fixtures. Rulings:

1. **The Extra work list hides nothing, and the chips are the
   server's phases.** Since W-NAV1.2 the list filtered its fetched rows
   down to "no operational ticket yet" and counted the chips over what
   was left, so a tenant whose every request had become a ticket saw
   zero rows under zero chips while the API returned all of them
   (web-Claude's seed: 16 hidden of 16; crmtest: 67 hidden of 99).
   Every row the server returns is now listed; the chips bucket rows
   by `display_phase` (FE-2's one phase, exhaustively mapped — a new
   phase fails to compile); the row badge is the same phase; a guard
   line under the tiles says how many rows were loaded and refuses to
   stay quiet if the chips do not add up
   (`extra-work-list-loaded-count`, `extra-work-list-guard`;
   `tests/e2e/p8_extra_work_list_guard.spec.ts`;
   `extra_work/tests/test_p8_truth.py::ListNeverHidesAServerRowTests`).
   Dashboard deep links with `?status=<ExtraWorkStatus>` land on the
   phase chip that status normally sits in. The money tile never
   prints a dash: "Laden…" while loading, "Nog geen prijs" when every
   request behind it is unpriced.
2. **The plan door does not start the work unless asked.**
   `POST /extra-work/<id>/plan/` and bulk-plan used to read an absent
   `start` as "plan AND start". Inverted: absent means do not start;
   only `start: true` starts. Every caller sends the key explicitly
   (the EW plan modal `false`, the ticket page's mirror `false`, the
   bulk dialog its switch — now OFF by default). Zero migrations. The
   audit's attack is pinned: an unpriced quote work with a crew and a
   date does not start even with `start: true`
   (`test_p8_truth.py::PlanDoorStartIsExplicitTests`).
3. **Refusals render at the acting control, in the reader's words,
   with their door.** `lib/extraWorkRefusal.ts` is the twin of P-5's
   ticket describer for every meerwerk door: `plan_requirements_unmet`
   names the missing pieces and offers "Plan aanvullen" (opens the plan
   modal at the first gap); `override_reason_required` offers "Reden
   opgeven" (opens the amber reason modal); every other stable code and
   every DRF field validation has its own sentence; "That was not
   accepted" survives only for a detail-less 5xx. The sentence renders
   under the banner for the primary action, in the Acties card for the
   folds, beside the proposal's buttons for the quote doors, and scrolls
   into view.
4. **The ceremonies.** A provider deciding a quote on the customer's
   behalf is amber (never green) on both doors (the proposal card and
   Geavanceerd) and confirms in the warning modal with the REQUIRED
   reason (the drawer's `RejectReasonDialog tone="warning"`); the
   inline reason form is gone. Send quote confirms with the lines, the
   total and "Send this price to <customer>?" (on the no-approval
   routes: "record this price and start the work"). Start the work
   asks once, naming the plan (people · manager · dates · hours) or
   the pieces it still misses. The Preview / Quote PDF pair appears
   once per page: the lines card on the Money tab is its home; the
   Andere-stappen fold offers it only while another tab shows.
5. **Label truth.** The pricing gate needs hours above 0, satisfied by
   the per-person hours OR the budget; the plan modal's hours block now
   says so in one caption and the budget label says it is optional
   BECAUSE the per-person hours count.
6. **§5.1 verified with a real agreed price.** An agreed-only cart
   routes INSTANT, lands CUSTOMER_APPROVED / WAITING_PLANNING with one
   ticket, for the customer and for the provider creating on their
   behalf; an unpriced line waits for a price
   (`test_p8_truth.py::AgreedPriceRoutesInstantTests`; on crmtest T2
   and T6 in the P-8R matrix). The create page reads agreed prices from
   `GET /api/customers/<id>/pricing/` (`listCustomerPrices`), resolved
   client-side on the cart date the way `pricing.resolve_price` does.
   Web-Claude's seed landed REQUEST_QUOTE because its service had no
   agreed price for that customer.
7. **Findings of the matrix walk that landed in this sprint.** A
   customer could reject a sent quote on the PROPOSAL door with no
   reason while the request door refused it — the proposal door now
   answers `rejection_note_required` (pinned). The P-7 hours modal had
   lost its backbone: a person x building pair whose saved hours were
   all on jobs had no standard row at all ("1 person x 2 buildings = 1
   standard row"); an untagged seed now yields only to a saved
   untagged or CONTRACT row, never to a job-linked one.
8. **The hours modal is the pre-P-7 base plus three things.** Kept
   from P-7 S1: the switch-week ask, the save math, the one count.
   Restored: the coloured type/job labels, the explanatory count
   ("2 people x 2 buildings = 4 standard rows (+2 job rows)", counted
   in blocks so "+ Add type" cannot change the arithmetic), the
   standard rows as the visible backbone; job-linked rows are
   indented, labelled children ("on Ticket #374") under their person.
   The fill tool is a normal toolbar row above the table; the dialog
   is `min(96vw, 1240px)` with a fixed column layout, no sideways
   scroll at 1440 (modal scrollWidth 1238 = clientWidth 1238).
9. **Settings, designed.** Header band: avatar with a pencil upload,
   name, email, role chip, one quiet meta row (member since · last
   sign-in · access as "3 companies · 29 buildings · 4 customers").
   Below: Profile / Password side by side, Notifications spanning —
   `minmax(0,1fr) minmax(0,1fr)` at 1440 (555px + 555px measured), one
   column under 1100px (820 measured 524px). No dead half.
10. **My schedule card facts.** A real deadline prints its date AND its
    countdown in one chip ("deadline Sep 1, 2026 — 2 days left"); a
    row waiting for the customer says "Klaar gemeld op <date> — wacht
    al N dagen op de klant", the date being the moment it was REPORTED
    done (`reported_done_at`, server-computed from the status history —
    the walk caught the row printing the planned day instead); the
    "Wacht op klant" chip is GLOBAL across week browsing (the server
    already returned the whole scope; the client hid the chip outside
    the current week — §D.15 rule 1's "past and future weeks keep
    placement as history" still holds for the columns); an unfinished
    job planned earlier this week or last week rolls into today's
    column with its "Gepland <day> — N dagen te laat" marker and shows
    in its own historical week as history; the board's teaching line states the one
    card standard (what and where · one status line · at most one time
    chip: clock, else after-deadline, else deadline with countdown, else
    the day window; without a plan: created on). Every lane reads the
    same standard.
11. **Pages that say what they are.** Contracts opens with "Wat er met
    elke klant per locatie is afgesproken: bedragen, uren en looptijd."
    and its rows link the customer and the buildings; Invoices opens
    with "Facturen worden gevuld met afgerond meerwerk per klant en
    maand, en met de vaste contractperiodes." (both feeds, truthfully)
    and its rows link the customer.
12. **Queued by name, not fixed here.** (a) A proposal line the
    operator priced wears the source tag "Agreed price"
    (`invoice_row.source.agreed_price` for any own unit price) — a
    quoted price is not an agreed one; wording is the owner's call.
    (b) A ticket spawned from an agreed-price cart starts with no crew
    and no day of its own; the start refuses with
    `transition_requirements_unmet` until both are set on the ticket
    (the request's crew carries over only where one was assigned
    before the spawn) — by design, but the Werkplanning is where the
    operator learns it, not the request. (c) Settings' "last sign-in"
    reads the JWT login only when the token door updates `last_login`.
    (d) **An unfinished job planned in a PAST week is absent from that
    week when browsed** (`views_work_plan.py`: a job that rolls forward
    is dropped from any week that does not contain today — E3 on
    crmtest, planned Wed 19 Aug, still open, shows on today's board and
    nowhere in week 34). The P-8R walk contradicts the owner's "browsed
    in its historical week" expectation, but placing it there reverses
    FE-4/P-1's "one card, today's column" ruling that the §D.15 matrix
    tests pin; it waits for the owner's word: a history card in its
    original column ("Gepland hier — staat vandaag op het bord") or the
    current rule.
    (e) **A day planned on the ticket AFTER a person was assigned does
    not reach that person's slot unless the planner ticks "also apply
    to the people"** (`POST /tickets/<id>/schedule/` `apply_to_slots`,
    default false — P-5's one-plan-one-date wiring). The manager's board
    then shows the job on its day while the person's own My schedule
    lists it under "Not planned yet" (E1–E3 on crmtest, tickets 431–433).
    By design, but the two views disagree about one fact; the default
    is the owner's call.

## D.21 Find your way — the P-9 rulings (2026-09-01)

Web-Claude's audit of the P-8R deploy and the owner's walk named the
same thing three ways: work that exists but cannot be FOUND — a started
meerwerk hidden from every list, a schedule board that files finished
work under the day it was planned, a Tickets page that opens empty on
the first of the month. P-9 (`feat/p9-find-your-way`) is the round that
answers "where is it?" the same way on every surface. Rulings:

1. **The schedule law (Part A).** The owner's model, verbatim in plain
   words: *"Today shows what is planned for today and what I didn't do
   yesterday. The past shows only what I finished. The future shows
   what I will do. Not-planned and waiting-for-the-customer are outside
   the dates."* `tickets/work_plan.py` states it as rules 9 and 10:
   - **Four zones, always visible, in this order:** *Not planned yet —
     N* (a section, not a toggle; the count is the section title in the
     page's h2 size; each row: what · where · the one card fact line ·
     one button **Plan it**, which opens a small dialog with today
     pre-filled; Parked stays as the quiet fold under it), *Waiting for
     the customer — N* (same shape; no action on the row except Open —
     the reminder lives on the request, and deciding for the customer
     lives behind the ticket's own Geavanceerd, so P-4's amber
     approve-on-behalf button left the row), the **week board**, and
     nothing else above the board: the status chips, the source
     select, the search box and the two "elsewhere" doors (late any
     week, planned later) fold behind ONE **Filter** button (P-2's
     rule); the "how does this board work?" fold is gone.
   - **A day column holds, per direction:** today = planned for today +
     every unfinished job whose planned day has passed (rule 5) +
     review rows (rule 8); future days = planned work only; **past days
     = finished work only, placed on the day it was FINISHED.** Two
     changes carry that: (a) a job waiting for the customer leaves the
     columns of EVERY week, not only the current one (rule 9 in every
     week — "when it goes to customer approval it leaves the dates");
     (b) a finished job hangs on its settled day (rule 10):
     `Job.settled_day` is the local date of the finish moment — the
     worker's report (`manager_review_at` / `sent_for_approval_at`),
     else approval / close — the same stamp the card prints
     (`detail_facts.ticket_finished_at`), so a card can never sit in
     one column and name another; a finished job with no known finish
     moment (legacy rows) keeps its planned window. The SQL twins carry
     a `settled_day` annotation on every source and the parity tests
     hold (`test_p9_schedule_law.py::CountsAgreeWithTheLawTests`).
   - **Ruling 12(d), closed by the owner's words:** an unfinished job
     planned in a past week is NOT in that week — it is on today.
   - **Ruling 12(e), decided:** `POST /tickets/<id>/schedule/`
     `apply_to_slots` defaults **true** on every door (serializer,
     `set_schedule`): one plan, one date — when the job's day moves,
     every person's slot on it moves too; the modal shows the box
     ticked with "Everyone on this job moves with it." The manager's
     board and a worker's own schedule can never disagree about the day.
   - **Ruling 12(b), decided:** an unplanned ticket's schedule card IS
     the "Not planned yet — plan it" row (the lane's words); a start
     the server would refuse (`transition_requirements_unmet`: no crew
     or no day) is a DISABLED button with the reason beside it and a
     door to the schedule card — the screen says so before the click
     (§D.6 rule 14). The page asks the same `transition-requirements`
     endpoint the modal asks.
2. **The one card fact standard (§A.3).** One sentence per state, the
   same sentence on the board's cards, the two zones and the detail
   headers (`components/workplan/cardFact.ts`); no surface writes its
   own version. The table:

   | state | line |
   |---|---|
   | not planned | created {date} by {who} · deadline {date} ({n} days left / over) — or "no deadline" |
   | planned, future | planned {weekday date} · {n} h · {people} · deadline {date} ({relative}) |
   | planned, today | same, first word "Today" |
   | rolled onto today | planned {weekday date} · {n} days late · deadline … |
   | reported done, manager check | reported done {date} by {who} · waiting for your check {n} days |
   | waiting for customer | reported done {date} · sent to {contact} · waiting {n} days |
   | finished | planned {date} · finished {date} ({n} days after the plan / on the day) · approved {date} when later |

   A deadline is always date AND relative; "planned" is only ever a day
   a person chose (P-1). The board's due chip is gone from the card —
   the line carries the deadline; the time chip keeps only what the
   line does not say (a real clock, "planned after the deadline", a
   multi-day window). The work-plan entry carries the facts the line
   needs, server-computed: `reported_done_by_name`, `waiting_days`,
   `approved_at`, `sent_to_name` (the customer's person who opened the
   melding, else the organisation), `planned_hours` (the request's
   budget, else the sum of its per-person rows; a worker's own hours on
   their own slot), `settled_days_after_plan`, and the three moments as
   server-decided DAYS (`settled_day`, `reported_done_day`,
   `approved_day` — P-3 §A.3, never a slice of a UTC instant).
3. **Same law for every viewer (§A.4).** SA and manager read the team
   scope, staff their own jobs: identical zones, identical sentences.
   Customers have no board (§D.3).
4. **Extra work: four tabs (Part B).** `/extra-work/:tab`, URL-backed
   like the People page, `/extra-work` landing on the first tab with
   rows (else To price): **To price** (WAITING_PRICE; sub-chips All ·
   Goes to the customer after pricing · Starts as soon as it is priced),
   **With the customer** (WAITING_CUSTOMER_APPROVAL, REJECTED; Waiting ·
   Declined), **Approved, in the works** (WAITING_PLANNING, SCHEDULED,
   IN_EXECUTION, WAITING_COMPLETION_APPROVAL; All · To plan · Planned ·
   Busy · Done, check it), **Finished** (DONE, INVOICED; All · To invoice
   · Invoiced). Cancelled is not a tab: a text link at the foot of
   Finished opens the same table filtered to cancelled. The tab label
   carries its count; the P-8 guard (server count = tabs + cancelled)
   stays as a quiet footer line, red only when it fails. The tab table
   is ONE exported Record over `ExtraWorkDisplayPhase`
   (`lib/extraWorkTabs.ts`): a new phase fails compilation, and
   `extra_work/tests/test_p9_tabs.py` pins that every server phase maps
   to exactly one tab or to cancelled. Per tab at most six columns and
   ONE next-step button from `nextStep.ts` (the detail page's one
   source): Price it / Price and start; Remind the customer (after 3
   days, else Open); Plan it / Check the work / Open; Go to invoices /
   Open invoice. One money sentence per tab from the loaded rows. Gone:
   the "Quoted, not yet started" tile, the total-value line, the seven
   open filter dropdowns (folded behind Filter, customer-first), the
   route / category / department columns. Recurring work stays on its
   own page (B5). Decided while building (the reference mockup was not
   on disk): the "To price" split reads `request_intent`
   (AUTO_START_AFTER_PRICING = "Starts as soon as it is priced",
   everything else = "Goes to the customer" — `display_phase.py`'s own
   branch); sub-chips are the composer pills, every tab with an "All"
   chip first; dashboard `?status=` deep links land on the tab holding
   that status with its chip preselected; "Remind the customer" opens
   the request's messages (no reminder endpoint exists); the list row
   gained eight additive read-only facts (`line_summary`,
   `contract_estimate_amount`, `people_names`, `rejection_note`,
   `completed_at`, `invoice_ref`, `contact_name`,
   `customer_invoice_day` — the last three provider-only), loaded
   once per page, query growth pinned at zero; the customer admin
   embed keeps the tab in `?tab=`; `phase.ew.SCHEDULED` reads
   "Planned" in EN like `phase.ticket.PLANNED` (one word per concept).
5. **Vocabulary (B2).** `phase.ew.WAITING_PLANNING` = "To plan" / "Nog
   plannen"; `phase.ew.IN_EXECUTION` and `phase.ticket.IN_EXECUTION` =
   "Busy" / "Bezig" (the Tickets tab's word); `WAITING_COMPLETION_
   APPROVAL` = "Done, check it" / "Klaar, controleer". The EN bundles
   no longer contain the Dutch word "meerwerk" (§D.2: one word per
   concept per language).
6. **Extra work create and money (Part C).** "Something else" is a box
   that adds only on Add (disabled with its reason while empty; a
   typed-but-not-added line at submit is an amber question, never sent
   silently). The plan modal's budget is "Total planned hours", needed
   before pricing, marked as such, saveable at 0. Every requested line
   is in the Pricing table: a cart line without a quote line renders
   as an unpriced row ("needs a price"; pricing it creates the quote
   line from the cart; "Leave it out" drops it). The Send / Start /
   Approve-on-behalf confirms carry the coverage check
   (`lib/extraWorkCoverage.ts`, one `CoverageNotice`): fewer / more /
   quantity differs make the confirm amber and the primary button says
   what it does ("Start with 2 of 3", "Send 4 lines (1 extra)", "Send
   the price"). Hours worked are entered only once the work has started
   (IN_EXECUTION → DONE; read-only after INVOICED). **Ruling 12(a),
   decided:** a quote line's source badge says "Contract price" only
   when it came from the contract pricing; a line the operator priced
   says "Your price"; custom cart lines say "needs a price" until
   priced — no field was added: `price_source` already carries the
   provenance (CONTRACT only when the line has a service and its price
   equals the applicable contract row), pinned by
   `extra_work/tests/test_p9_price_source.py`; a customer reading the
   same table sees "Quoted price". No helper sentence about something
   the screen does not show (C7; the removed sentences are in the P-9
   report). Decided while building: the old per-line optional note
   left with the box (the request's description carries particulars);
   the start / approve-on-behalf ceremonies name an uncovered line
   without the "unless you add it" door, because the quote cannot
   change any more; the "hours worked are entered once started" card
   renders for WAITING_PLANNING / SCHEDULED only. Frontend unit tests
   run on vitest (`npm run test:unit`), added on this sprint's explicit
   ask.
7. **One Tickets queue (Part D).** The `is_extra_work=false` default is
   gone: the Tickets page shows every operational ticket with an
   **Origin** column (Melding / Extra work / Recurring / Ticket, from
   the server's `kind`) and Origin in the Filter fold; the four tabs
   keep their counts visible; a tab's empty state points at the others
   — and names the period when the period narrowed the list (the
   Tickets page opens on this month; on the 1st that is empty by
   design, and the sentence offers "Show all time"). The Extra work
   page is the money view, the Tickets page the operational view.
   The Origin filter is a server-side `?origin=melding|meerwerk|
   recurring|ticket` on the list AND on `stats` (never `?type=REPORT`:
   on crmtest every one of the 91 extra-work tickets is typed REPORT
   too), partitioning rows exactly as the column labels them;
   `hide_finished_extra_work` is no longer sent by the Tickets page
   (finished work of every origin lives on the Done tab). Hours: an
   empty week says where the hours are ("No hours saved for week 36
   yet. Last saved week: 35 (312 h)", Open week 35, Enter hours worked)
   and a full-year week strip under the week bar marks the weeks that
   hold hours (`GET /api/timesheets/weeks/with-hours/?iso_year=`, one
   aggregate query in the entries list's own scope; no server cache —
   `settings.CACHES` is not configured — the pages refetch it with the
   entries). Open question for the owner, from D1: with the
   `this_month` default the Open tab opens empty on the 1st of every
   month; a status pile narrowed by creation month hides open work for
   being older.
8. **Settings (Part G).** Profile and Password cards are equal height.
   **Ruling 12(c), decided:** "Last sign-in" shows the last token issue
   time if it is recorded; if it is not, the line is removed — a fact
   the system does not know is not shown. It is NOT recorded (SimpleJWT
   without `UPDATE_LAST_LOGIN`; the token view does not touch
   `last_login`), so the row is gone; the setting was not switched on.
9. **Process.** A report about commits that are not on `origin` is a
   report about nothing: `feat/p8-truth` was pushed as P-9's step 0
   and the rule is in CLAUDE.md §1 beside "CC pushes branches".
10. **Queued for P-10, not started:** Contracts and Invoices calm-down
    (a draft contract with no lines shows one card and one button;
    "Projects" → "Lines"; contracts list ≤5 columns; Invoices
    "Generate" → "Make a draft" with "nothing is sent until you send
    it"; the creator e-mail under draft numbers goes); SLA warnings as
    an approved reference page (one purpose sentence, one action per
    row); the guidance layer on admin surfaces (every completing action
    says what happened and the one next step, with one link — the
    melding-flow voice, system-wide).
