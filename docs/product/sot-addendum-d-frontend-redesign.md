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

- **Werk:** Dashboard, Werkqueue (tickets + meerwerk-execution with type
  pills; "Chargeable work" becomes a saved filter), Meerwerk (commercial
  pipeline: quotes/pricing/approvals), Terugkerend werk.
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