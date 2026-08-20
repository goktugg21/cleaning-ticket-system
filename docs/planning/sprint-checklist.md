# Osius — Gap-Closing Sprint Checklist

**Purpose.** The living plan to close every remaining gap between the
system and the Ramazan transcripts + Source of Truth, ending with a
premium UI/UX polish. **CC updates `## NOW` / `## NEXT` / `## SHIPPED`
in the SAME branch as the work** — this file drifted twice because the
update was left for a later docs-only pass.

<!-- Sprint 176 §8: the sentence above was truncated mid-word by Sprint
     175's own edit ("**CC updates `## NOW" and then straight into the
     branch line), which also left the file with TWO `## NOW` headings.
     Restored, and the older section below is now labelled as history. -->

## NOW

**Branch:** `feat/ew-gap-closing`. Sprints 153–189 land as ONE PR into
`main` — a fast-forward, and the first time CI runs on any of it. The
owner opens and merges it.

Sprint 189 runs as THREE parallel Claude Code chats on this one branch,
on disjoint file sets: chat 1 the two detail pages, chat 2 the backend,
chat 3 the list and dashboard pages. The plan they execute is
[docs/planning/ew-gap-closing-plan.md](ew-gap-closing-plan.md).

Sprint 187 shipped, then was VERIFIED rather than believed, and the
verification found real defects in it. Those became 187C. 187B ran in a
parallel Claude Code chat on a disjoint file set and merged into the same
chain with zero conflicts. 188 is the owner's closing round.

<!-- Sprint 187 §8: this section read "Branch: feat/sprint-181" while the
     chain was at 186 — three sprints of drift, and the second time this
     file has done it. The rule in CLAUDE.md §8 and in "How to maintain
     this file" below is the same one it was already breaking: NOW /
     NEXT / SHIPPED are updated in the branch that makes them stale.
     Sprint 188 §docs: brought to the head of the chain again, and the
     NEXT queue below was re-verified item by item against the code
     rather than carried forward on trust. -->

### Done — W4-N (wave 4, chat N of 6): contacts beside the whole card, and the hours card

Two owner corrections on the Extra Work detail page. Frontend only — no
backend file was opened, no migration, no test-runner change.

**Fix 1 — Customer contacts starts at the TOP of the Details card.** The
third attempt at this. W2-B split only the LOWER half of the card, so the
contacts heading began level with "Description"; W3-F kept that split and
merely removed the panel's padding. Both left contacts most of a card
below "Building", which is not what was asked for. The split now starts
directly under the section title and holds both fact grids, the dates
editor and the prose in its left child, so the card reads as three
columns from its first row.

The acceptance number, measured in the live DOM at 1440px with twelve
contacts: the "Building" label's top is **y = 269** and the Customer
contacts block's top is **y = 269** — **delta 0.00px**. Same two numbers
at 1280px: **269 / 269, delta 0.00**. The contacts heading itself is also
at **269**. Alignment is structural, not a tuned margin: both are the
first child of row one of an `align-items: start` grid.

- **The list still scrolls inside its own box and the card does not
  stretch.** Twelve contacts: list `clientHeight` **300**, `scrollHeight`
  **1240** — it scrolls. The Details card measures **927px** with twelve
  contacts and **927px** with two. Identical.
- **"Edit labels" still moves nothing below it, and now at 1280px too.**
  Description y **567 → 567** and routing y **855 → 855** at 1440px;
  **585 → 585** and **873 → 873** at 1280px. That second pair needed a
  fix: narrowing the fact grid made the read state's ONE icon button fit
  beside the values where the edit state's TWO did not, so the cell
  wrapped differently per state and pushed everything below it down
  **36px** — one `.btn-sm` row plus the flex row-gap. W3-F's parity rule
  rested on the two states being the same HEIGHT; they now also have the
  same WIDTHS (equal flex bases on both label/value stacks, and an action
  slot that reserves two icon buttons in both states), so wrapping is a
  property of the cell and not of the state. Labels cell measured at
  **1440 / 1366 / 1280 / 1152px**: identical height (118px) in both
  states at every one.
- **Horizontal page overflow is 0** at 1440 and 1280, closed and open.
- **A role that may not see contacts still gets the full-width card.**
  `.ew-detail-cols-main:only-child` spans both columns — measured by
  removing the panel from the live DOM: main **272.7 → 588.7px**, the
  wrapper's full **588.7px**.

**Fix 2 — the hours panel is a collapsible card, moved and regrouped.**

- **Same card as Requested services, not a second idiom.** It mounts
  `CollapsibleCard`, the component Requested services uses. Measured
  side by side: chevron **16x16**, `rotate(-90deg)` closed, colour
  `rgb(138,155,145)`, header padding `16px 22px`, header height **48px**
  — identical on both cards.
- **Closed by default**: `data-open="false"` on first render, and zero
  `.collapsible-card-body` nodes exist while closed.
- **Moved** to below People on this request and above Requested services.
  Card tops at 1440px: People **1513**, Hours **1579**, Requested
  services **1645**.
- **The collapsed header carries the over/under-budget figure**, in
  Requested services' own grammar (volume, then the one figure). All four
  readings, measured from the rendered header (nl, the primary bundle):
  over `"8,50 uur geboekt · 2,50 uur over de begroting"`; under
  `"8,50 uur geboekt · 3,50 uur onder de begroting"`; exactly on budget
  `"8,50 uur geboekt · Precies op de begroting"`; **no budget set**
  `"8,50 uur geboekt · Geen begroting om tegen af te zetten"` — never
  "0 over", which would claim the job landed on a budget nobody set. A
  zero variance and an absent budget are deliberately different
  sentences. Header height **48px** and page overflow **0** in all four.
- **The open state groups the figures by what they are.** Five equal
  bordered boxes became two groups: Budget → Entered as ONE comparison
  with the arrow between them and the variance sentence under it,
  Weighted as a subordinate line beneath (it is Entered times a factor,
  not a sixth headline), and Labour cost + Travel in their own tinted
  group — measured `rgb(242,244,242)` against the hours group's
  `rgb(255,255,255)` — because money is not an hour. "Not budgeted"
  renders as muted text, not as a figure.
- **The provenance line survives**, as required: it is the first thing in
  the opened body, above every figure it explains — "Uren komen uit de
  urenregistratie; loonkosten worden berekend in rapportage. Op dit
  scherm staat geen uurloonveld, en dat is met opzet."
- **No arithmetic was added.** Every figure is still a fixed 2dp string
  the server produced; the only numeric operation in the component is the
  existing `Math.abs` that strips a sign the sentence already states.

**i18n.** Three keys added to both bundles (`hours_panel.group_hours_title`,
`hours_panel.group_money_title`, `hours_panel.meta_entered`); nl and en
both **592 keys**, symmetric difference empty.

**Gates.** `tsc --noEmit -p tsconfig.app.json --listFiles` exit 0 over
**849 files, 300 of them under `src/`**; `eslint .` **44 problems (42
errors, 2 warnings)** — the baseline exactly, no new violation and no new
`eslint-disable`; `vite build` OK. No test runner was added and no
backend test was run: the sprint touches no backend file.

### Done — W4-M (wave 4, chat M of 6): the ticket header, the customer's Workflow card, and two photo scopes

Frontend only. `TicketDetailPage.tsx`, the ticket-header and
ticket-workflow blocks of `index.css`, and the `nl`/`en`
`ticket_detail` bundles. Every number below is read off the live DOM
against the same page built from the branch point in a second
worktree.

- **§1 — the header block is smaller, and it has some craft now.** It
  stays PLAIN TEXT, which is the point Sprint 191 took three attempts
  to reach: measured computed `background` `rgba(0, 0, 0, 0)`, `border`
  `0px none`, `box-shadow` `none`. What changed is the type scale and
  the labels. Values **18px/800 -> 15px/700**, labels **11px -> 9.5px**
  with a 10px lucide glyph in front of each (a pin for Location, people
  for Customer), the building sub-line **13px -> 11.5px**. Measured
  block height on the real seed row at 1440px: **91px -> 81px**; at
  1280px **87px -> 81px**. On a stress row (a 48-character room label
  and a 52-character customer name) **153px -> 138px** at both widths.
  The block still ends flush with the Convert-to-Extra-Work button
  (right edge **1412px** at 1440, **1252px** at 1280) and page overflow
  is **0** in all eight runs. The label colour moved from
  `--text-faint` to `--text-muted` in the same pass: at 9.5px the old
  tone was **2.75:1** on the page ground and unreadable; the new one is
  **5.31:1**.

- **§2 — "No status transitions available for your role." is deleted.**
  A customer opening their own job was told what their role cannot do,
  which is worse than being told nothing. In its place the card now
  states where the job IS: a "Current status" micro-cap, the status name
  at **20px/800** with a status-coloured 9px dot, and the time it
  arrived there, read off `status_history` rather than any one timestamp
  column. Measured from an ACTUAL customer session (Bright Facilities
  customer, ticket 11): the sentence is gone from the page text, the
  readout renders at **275x62px**, the dot is `rgb(11, 107, 66)` for
  IN_PROGRESS, and the since-line reads "Sinds 20 jul 2026, 01:11".
  The path where a customer CAN act is untouched and was verified
  separately on a WAITING_CUSTOMER_APPROVAL ticket.

- **§3 — the provider company name on the customer's view is real
  data, verified rather than assumed.** Logged in as a customer of
  Bright Facilities (a DIFFERENT provider company from the demo's Osius
  Demo) the assigned-staff heading reads "Toegewezen **Bright
  Facilities**-medewerkers". It interpolates `ticket.company_name`; no
  change was needed.

- **§4a — the per-work photo switch finally has a mount point.**
  `Ticket.staff_uploads_customer_visible` and its endpoint shipped in
  Sprint 191 §2.5 with no UI anywhere. It is now a switch at the top of
  the Attachments card, PA/SA only, disabled on a terminal ticket with
  the reason stated. The caption says in words that flipping it decides
  the NEXT upload and releases nothing already stored — in amber, not
  muted grey, because a manager who misreads that line believes they
  released yesterday's photos and did not.

- **§4b — the per-ticket half of the staff pre-permission, against
  chat P's contract.** On the Assignment card, one row per assigned
  person, three states (not two): grant, refuse, or leave it to the
  company-wide setting. The scope is in the heading ("Photo permission
  — THIS JOB ONLY"), in the helper, and in every option label, because
  there are two controls in this product that look alike and mean
  different things and the owner asked that nobody have to guess which
  one they flipped. Each row also states what the next photo would
  actually do and which rung of chat P's ladder decided it.

### Done — Sprint 191 (wave 3, chat E of 2): Location & Customer, third time

The owner asked for these two facts in the page HEADER three times. Sprint 189
built a card in the right column; Sprint 190 moved the same card up one slot.
Both readings were wrong, and both were mine. This is the header.

- **§1 — plain text in the header band.** The header is now a two-column band:
  ticket-number chip row + title + description on the left, Location and
  Customer on the right, right-aligned, directly under the Convert-to-Extra-Work
  button. Measured at 1440px: the block's right edge is **1412px** and the
  Convert button's right edge is **1412px** — flush. The block spans y
  **126–419**, the chip row starts at y **126** and the title at y **158–237**,
  so it opens level with the top of the band and runs the full height of the
  title. Values render at **18px/800** against the title's 36px. It is plain
  text and measurably so: computed `background` is `rgba(0,0,0,0)`, `border` is
  `0px none`, `box-shadow` is `none`.
- **The block is not tied to the button.** On a CLOSED ticket, where
  `canConvertTicket` is false and no button renders, the block is still there
  and settles **2px upward** (y 126 → 124) as the row above it shrinks. No space
  is reserved, nothing disappears, no hole.
- **§2 — the card is deleted.** Element, CSS block and `data-testid` all gone;
  `.ticket-place-card` no longer appears anywhere in `src/`. The right column is
  five cards again, measured in the DOM on every ticket:
  `side-card-workflow` → `side-card-assignment` → `responsible-managers-section`
  → `ticket-schedule-card` → `side-card-details`. No e2e spec referenced the
  testid, so no test needed updating.
- **Location and Customer are STILL in the Ticket details card.** Verified by
  expanding it: the first two rows read LOCATION and CUSTOMER on all three
  tickets measured. That has been right since Sprint 189 and was not touched.
- **Overflow, under stress.** With a 121-character room label and a
  106-character customer name the block wraps inside its 300px ceiling and
  `document.scrollWidth` still equals `clientWidth` (1440) — zero horizontal
  overflow. At 390px the band stacks, the block goes left-aligned at 17px, and
  overflow is still 0.
- `docs/planning/ew-gap-closing-plan.md` §2.1 **items 4 and 5** are corrected in
  the same commit, with both superseded orders quoted inline so the next chat
  can see what changed rather than trusting a silently-edited line.

**Gates.** `npm run typecheck` clean over 295 project files; `npm run lint`
exactly 44 (42 errors, 2 warnings); `npm run build` OK. No i18n key added — the
header reuses the existing `details_location` / `details_customer`.
### Done — W3-G: the completion gate stopped asking every job the same question

Plan §2.3, item 7's server side. W2-D stored `file_upload_required` and
`completion_notes_required` on the extra work and deliberately left
enforcement to wave 3; this is that enforcement. **No migration** — the
two columns already exist and nothing was added to any model.

- **The rule is configurable and the two flags are independent.** File
  only, note only, both, or neither — the four combinations, on the
  work, set when it is planned.
- **It is enforced on BOTH completion surfaces, from ONE rule.** New
  `backend/tickets/completion_requirements.py` answers "what does this
  job need"; the per-slot gate
  (`views_staff_assignments._SlotWriteSerializer`) and the ticket-level
  STAFF completion transition (`state_machine.apply_transition`) both
  call it. Only the slot gate was named in the brief, and only the slot
  gate would have been a hole: it does not move the ticket, so a rule
  binding it alone is walked around by moving the ticket instead — and
  the ticket transition is the one that makes work billable.
- **A ticket that came from no extra work keeps exactly the rule it had:
  a note or a photo.** There are no flags to read, and inventing a
  default would either drop a requirement live work has always been held
  to or invent one nobody asked for. The resolver reports `source`
  (`extra_work` / `default`) so a caller can tell "this needs nothing"
  from "we could not find out", and four tests pin the old behaviour so
  a later sprint cannot drift it by accident.
- **The two gates keep their own evidence pools, unchanged.** The slot
  reads what is linked to THAT slot — a sibling worker's photo is not
  proof this visit happened — and the ticket reads its own
  customer-visible attachments, message-tier exclusions and all.
- **The error message names what is missing.** "Completing a slot
  requires a note or a photo" was true of every job until this sprint
  and is now true of some of them, which makes it the worst kind of
  message: right often enough to be believed.
- **The worker is told before they fill the form in.** New read-only
  `GET /api/tickets/<id>/staff-assignments/<slot>/completion-requirements/`,
  gated to the slot's owner or a manager exactly like the PATCH. The
  dialog states the requirement, marks the required fields, and keeps its
  own button honest — and the server still refuses on its own, from the
  same resolver. In the system we are closing the gap against, both flags
  are checked in the browser only, in two screens that check different
  things, and no endpoint can persist them at all.

**Three things the owner should decide, none of them silently taken:**

1. **Both flags default False, so every EXISTING extra-work ticket now
   requires nothing where it used to require a note or a photo.** That is
   what "both False -> nothing required" means applied to live data, and
   it is the specified behaviour, but it is a real loosening on work
   already in flight. If the intent was "off means keep the old rule",
   the change is one line in `completion_requirements.requirements_for_ticket`.
2. **`file_upload_required` is satisfied by ANY non-hidden attachment,
   PDF included**, because that is what the field is named and what W2-D
   documented. The legacy note-or-photo arm keeps its stricter reading
   (a genuine image; a PDF mislabelled `image/jpeg` never counted and
   still does not). If it should mean a PHOTO, it is the `has_file`
   argument at the two call sites.
3. **Managers still bypass the gate.** B1
   (`system-business-logic-and-workflows.md` §4.4) scopes the
   ticket-level rule to STAFF actors, and this sprint changed WHAT the
   rule asks, not WHO it asks. So a manager can complete a job that
   requires a photo without one. Asserted in a test rather than left to
   be discovered.

### Done — W3-H: the hours screen (wave 3, chat H)

Plan §2.8 and decision 12. The model was already there — `TimeEntry`
has carried `source_type` / `source_id` since Sprint 173, so hours have
been attributable to an extra work for several sprints — and nothing
read them back against the job. This is that read, plus the roll-up.

- **An hours panel on the Extra Work detail page.** Worker x day x hour
  type, read-only, for the entries whose source is this extra work. The
  hour type is part of the row identity, not a decoration: four normal
  hours and two overtime hours on the same day for the same person are
  two different facts and never merge onto one line.
- **Planned and actual, side by side.** The roll-up shows W2-D's
  `budget_hours`, the hours actually entered, and the difference between
  them ("5,50 uur over de begroting"). This is the comparison the
  reference system cannot make at all: over there `hours_planed` is
  written by six code paths and read by nothing that decides anything,
  and all three of its guards are dead code.
- **Labour cost is computed in `backend/reports/labour_cost.py`** and
  nowhere else. `timesheets/` still records hours and weighted hours and
  never touches money — there is a test that walks every non-test file
  in that app and fails on the word `hourly_rate`.
- **The screen says where each number lives**, in one line under the
  title: hours come from the timesheets module, cost is computed in
  reporting, and there is deliberately no hourly-rate field on this
  screen. Decision 12 asked for exactly that, so nobody hunts for a wage
  field that does not exist.
- **Budget hours never touches money.** It sits beside the cost and does
  not feed it: cost is computed from the WEIGHTED ENTERED hours. Pinned
  by a test that multiplies the budget by a hundred and asserts every
  cost figure is byte-identical.

**The honest part about cost.** There is no wage anywhere in this
system — not on `User`, not on `StaffProfile`, not on `HourType`, and
`timesheets` is written never to hold one. Inventing that field would be
a payroll feature nobody asked for, in apps this sprint does not own. So
the rate is one deployment setting, `LABOUR_COST_HOURLY_RATE_EUR`, unset
by default, read by `resolve_hourly_rate` and by nothing else — the seam
a real per-person rate replaces. **Unset, every cost figure is NULL and
the panel says why.** It never prints EUR 0,00, because a cost of zero
would claim the work was free. Travel costs (`TimeEntry.travel_costs`,
real money somebody really claimed) are shown either way, and are never
folded into a "total" while the rate is missing.

**Who sees what.** SUPER_ADMIN and COMPANY_ADMIN see the company's rows
and the cost. A BUILDING_MANAGER is admitted to the panel and sees only
their OWN hours and no cost — the Sprint 182 §1 privacy floor, applied
by calling BOTH halves of the pair (`filter_time_entries_for` for the
tenant, `restrict_entries_to_self` for whose row it is), and the
response says `visibility: "self"` so the panel states it on screen
rather than letting a partial grid read as the job's total. STAFF and
every customer-side role are refused at the door: the panel reports on a
parent Extra Work, which the P0 staff-privacy decision (A4) closes to
STAFF, and a worker reads their own hours in the timesheets module where
the same pair applies.

**Measured, not eyeballed.** 1440x1000, the built app served from this
worktree against this branch's backend, real rows in the dev database.
The panel is the fifth card in the main column at y=1440, 1128px wide
and 269px tall. The five roll-up figures sit on ONE row (five children,
one distinct top offset), 217px each. `document.scrollWidth` equals
`clientWidth` (1440) — no horizontal page overflow — and no element
inside the panel overflows its own box. The grid's scroll box needs
neither axis at this size (1124/1124 wide, 102/102 tall). With
`LABOUR_COST_HOURLY_RATE_EUR=32.50`: 17,75 gewogen uren -> "Loonkosten
EUR 589,38 / Tarief EUR 32,50 per gewogen uur", travel EUR 12,50 beside
it, and the grid reading 4,00 / 3,50 / blank / 7,50 for the first
worker. A day nobody worked is BLANK, not 0,00.

**Gates.** `tsc --noEmit -p tsconfig.app.json --listFiles`: 846 files
listed, 297 of them under `src/`, 0 errors. `eslint .`: 44 problems (42
errors, 2 warnings) — the baseline exactly, none of them in the new
files. `vite build` OK in 8.73s. nl/en `extra_work.json` both 588 keys,
symmetric, 27 added on each side. Backend:
`reports.tests.test_w3h_extra_work_hours`, Ran 20 tests, OK.

**Click path (SUPER_ADMIN).** Extra werk -> open any extra work -> scroll
to "Uren op dit meerwerk", directly under the actual-hours card. The two
are neighbours on purpose and each says which it is: the card above
enters hours onto a PRICING LINE (what the customer is charged), this
panel reads the hours the crew booked in the urenregistratie (what the
job cost us). To see it populated: Urenregistratie -> week grid -> book
hours with the job picker set to this extra work.

### Done — Sprint 190 §§1–4 (wave 2, chat A of 4): what the owner saw on the test site

Wave 1 shipped, the owner opened it on crmtest, and four things were wrong.
Frontend only; no backend file touched and no backend test run.

- **§1 — Location & Customer moved ABOVE Workflow.** Sprint 189 put Workflow
  first. Measured in the live DOM, the rail now reads `ticket-place-card` →
  `side-card-workflow` → `side-card-assignment` → `responsible-managers-section`
  → `ticket-schedule-card` → `side-card-details`, verified in all eight ticket
  statuses the page can reach. The two facts that tell you WHICH job this is now
  sit directly under the Convert-to-Extra-Work button, above the control that
  changes it. `docs/planning/ew-gap-closing-plan.md` §2.1 item 5 says the new
  order — see the note in "What I did NOT do" about that file being untracked.
- **§2 — both new things came down.** The card's values 22px → **18px** (page
  title 36px, header description 17px, all measured on the same render), and the
  narrow-viewport step 19px → 17px, which would otherwise have been bigger than
  the base. The workflow button 53px → **48px**: the owner called 53px "a little
  bit fine", so this is a small step down and deliberately not a return to the
  42px it was before wave 1.
- **§3 — colour on the workflow buttons, keyed to MEANING.** The primary forward
  action is now solid `--green` with white text; a second forward move on the
  same step is a green outline; a rejection is `--red` on white. No new colour:
  every value is an existing token. The mapping is a `Record<TicketStatus,
  WorkflowTone>` so a tenth status cannot compile until somebody classifies it —
  a `Set(["REJECTED"])` would have painted it green in silence. Measured every
  button in all eight statuses, base AND hover: the lowest contrast anywhere is
  4.90:1 and no rejecting action is ever green. The base `.status-btn:hover`
  turned any hovered button green-tinted, so before this, hovering "Move to
  Rejected" painted it in the approve colour; both tones now own their hover.
  The solid button's hover deliberately keeps `--green` rather than lifting to
  `--green-2` the way `.btn-primary` does, because white on `--green-2` measures
  4.38:1 — under the AA floor for 15px bold text.
- **§4 — the chargeable pill was invisible for customers.** On
  `/my/meldingen` the label measured **1.11:1**. Not a colour choice: the pill
  is an `<a>`, and `.td-subject a { color: inherit }` (0,1,1) outranked
  `.work-type-pill-extra-work` (0,1,0), so the white was never applied. Fixed by
  doubling the class to (0,2,0) rather than `!important`. Now **5.09:1**, hover
  6.60:1, both over the 4.5:1 AA floor. Measured in all four container contexts
  the pill is dropped into: only `.td-subject` was ever broken (3.49:1 for a
  clone, 1.11:1 on the real page), and the other three read 5.09:1 identically
  before and after.

**Gates.** `npm run typecheck` clean over 295 project files; `npm run lint`
exactly 44 (42 errors, 2 warnings), baseline held, no new `eslint-disable`;
`npm run build` OK. No i18n key added, so the nl/en pair is untouched.

### Done — W2-D: the planning layer (wave 2, chat 4)

Branch `feat/ew-gap-closing`, plan `docs/planning/ew-gap-closing-plan.md`
§2.2 and the two flags of §2.3. Backend and API only — every frontend
file was out of scope by design, because three other chats are reworking
the pages this will eventually mount on. The plan modal and the bulk-plan
table are wave 3.

- **A work now carries what we said it would take.** `budget_hours` is
  the planned total, and it is distributed across the people on the job
  in a new model, `ExtraWorkPlannedHours` — one row per person, in the
  `extra_work` app (not in `tickets`, which is another chat's file this
  wave; not in `timesheets`, which has a deliberate no-money rule and
  holds ACTUAL hours, and "planned vs actual" cannot be one number
  comparing itself).
- **Requested dates and committed dates are now two separate stored
  pairs.** `preferred_date` -> `planned_end_date` (plus `deadline`) is
  what the customer asked for and what is owed;
  `provider_planned_date` -> `provider_planned_end_date` (the second is
  new) is what the provider committed to. The plan action writes the
  second pair and never the first, so planning can no longer move the
  date the provider is measured against, and "did we do what we
  promised, or what they asked for?" is a question with an answer.
- **Plan and start are one action.** `POST /api/extra-work/<id>/plan/`
  writes the budget, the committed window, the per-person hours and the
  two completion requirements, and then starts the work. A start that
  cannot happen is REPORTED, never raised: once the work has an
  operational ticket its status follows that ticket (Sprint 181 §1), so
  the response comes back `started: false` with
  `start_skipped: "operational_status_follows_ticket"` and the plan
  still lands. Throwing away a correct plan because of a state the
  operator can already see on their screen would be the wrong trade.
- **Bulk plan, `POST /api/extra-work/bulk-plan/`** — the same payload for
  many works, all-or-nothing, with one constant rejection body for every
  reason (H-1). **It carries both completion flags**, which is the whole
  reason it is written the way it is. Here there is ONE payload
  serializer and ONE writer, and both read every field — booleans
  included — by KEY PRESENCE: absent means untouched, so a bulk edit of
  the dates cannot touch a flag and a bulk edit of a flag is something
  somebody asked for. (On the reference side the evidence is stronger
  than the brief's wording: neither flag survives ANY plan write there.
  The modal sends them, the config-driven update persists neither, and 0
  of 78 live records has either set —
  `docs/reference/osius-reference-system/01-extra-work.md` §1.6, §3.6.
  The brief calls it "bulk plan writes both to false"; the mechanism
  differs, the consequence is the same.)
- **Both plan endpoints are JSON-only, and that is a correctness fix.**
  DRF reads a boolean that is ABSENT from HTML form input as `False` (an
  unchecked checkbox sends nothing), so with the default parser set a
  form-encoded plan that never mentioned a completion flag would have
  written it to False on every work it touched — the same defect,
  rebuilt by a framework default rather than by anybody deciding it. The
  payload carries a nested list that form encoding cannot express
  anyway. Pinned by a test on each endpoint.
- **Overrun warns. It never blocks.** Distributing more hours than the
  budget returns 200 with a `hours_overrun` warning naming the budget,
  the distributed total and the difference; the save has already
  happened. The warning is on the read surface too
  (`planned_hours_overrun` on the detail), so the manager approving the
  work sees it on the screen they approve from. The no-block rule is the
  business's own: over there the hard cap exists as a complete function,
  `validateTotalHours()`, is never called, and the model's boot carries
  `// Hours validation removed per user request`.
- **Hours belonging to somebody who has been un-assigned stay visible and
  stay counted**, flagged `is_assigned: false`. Over there the grid is
  built from the assignment list, so those hours vanish from the screen
  while staying in every total and nothing explains the difference (live
  work 474: 13.5 distributed hours against a budget of 1.00, no warning
  anywhere).
- **Budget hours never touches money.** Nothing in the planning module
  reaches a price; `rowAmounts()` and its server-side mirror stay the one
  billing-total rule. Pinned by a test that reads all six money fields
  before and after a 40-hour plan and asserts they are unchanged.
- **Planning is provider-only, and a customer never sees the budget or
  the distribution** — on the detail or on the list. The two completion
  flags stay visible to them: those are a promise about the evidence
  they will get, not a number about our own people.

**Click path (SUPER_ADMIN).** There is no button yet — this is the API
half, and the UI is wave 3. To see it: Extra Work -> open any
customer-approved job -> the detail response now carries `budget_hours`,
`provider_planned_end_date`, `planned_hours`, `planned_hours_total`,
`planned_hours_overrun`, `file_upload_required`,
`completion_notes_required` and `actions.can_plan`. Assign people first
(Extra Work -> the job -> Assignment) or the hours distribution refuses
them.

**Gates.** Ran 129 tests, OK. No frontend file was touched, so the
frontend gate was not run. The migration's rendered SQL is four
`ADD COLUMN` and one `CREATE TABLE` — no drop, no type change, no
backfill.

**Handoff to wave 3.** The Work Plan still places an extra work on
`preferred_date` -> `planned_end_date`
(`backend/tickets/views_work_plan.py` `_ew_week_q` / `_extra_work_job`),
i.e. on what the CUSTOMER asked for, even though a committed window now
exists beside it. Whether the plan should draw the committed window when
one is set is an owner decision, and the file belongs to another chat
this wave.

**Tests.** `extra_work.tests.test_w2d_planning` and
`extra_work.tests.test_w2d_bulk_plan` are new;
`extra_work.tests.test_extra_work_mvp` and
`extra_work.tests.test_m4_billing_fields` were run because model fields
and both request serializers changed and those two modules are what
prove the existing shape is untouched. `extra_work.tests.test_sprint176_dates`
and `test_sprint184_dates_travel` were added to the list because
`dates.py` — the ONE writer of an Extra Work's dates — gained the new
committed-end field and its two validation rules.

**Not done, deliberately.** No enforcement of the two completion flags
(that is the completion transition, wave 3, and it belongs in one place).
No coordinator concept — the word does not appear in the reference
backend at all. No hard cap on hours. No `planned_by` / `planned_at`
columns: the plan writes one `ExtraWorkStatusHistory` annotation row,
which is the trail this app already uses for non-status writes, and a
second copy of the same fact is how two screens end up disagreeing.
### Done — W2-C: fifteen things above the table became eleven

The owner, on the Extra Work page: *"there are a lot of chips and cards.
it looks confusing make them simpler. without giving up important
information."* Frontend only — no backend file was touched and no
backend test was run, because nothing on the server changed.

MEASURED at 1440x1000 as SUPER_ADMIN against the seeded dev database,
before and after, from the live DOM. `/extra-work` put **953px** between
the top of the page and the first row of data; it now puts **728px**.
`/tickets/chargeable` went 750px to 681px. Nothing scrolls sideways at
1440 or at 1280 (`scrollWidth == clientWidth` on both).

- **The four KPI counter cards are gone (89px, four boxes).** Three of
  their four numbers were on screen twice. "Open requests 3" is the
  "Awaiting pricing" chip, which shows the same 3 AND filters; "Awaiting
  customer 1" is the "With the customer" chip, same. Those two are
  covered with nothing lost. "Price approved 3" is a REAL removal: since
  Sprint 180 split the list into two tracks, that number is split with
  it — the red "3" badge on the Quote & price tab counts the half with no
  operational ticket (the same 3, on this data) and the ticket chips on
  Chargeable work show the other half. There is no one place left that
  states it, and inventing one would have meant a chip whose count
  duplicates the badge beside it.
- **"Total value EUR 8,315.12" moved instead of dying.** It sits on the
  list's own toolbar now, as a sentence, above the table it describes.
  Its ARITHMETIC IS UNTOUCHED — measured identical before and after —
  because relocating a number must not change it. Beside the money strip
  it read as a fifth figure of the same kind and it is not one: the
  strip's four are server aggregates over precise populations, this is
  the sum of what the page loaded. That row was provider-only (the edit
  toggle inside it is); it renders for everyone now, with the toggle
  keeping its own gate, so a customer does not lose a number they had.
  **Known and deliberately not fixed here:** it still sums the loaded
  set, not the filtered view, so it can disagree with the rows on screen.
  Re-scoping it is the right fix and is in NEXT — it changes a number,
  which a layout sprint should not do quietly.
- **The track control, its sentence and the status chips are ONE band.**
  Three stacked blocks costing 58 + 19 + 55px plus gaps, two of them
  rendered as identical rows of tiles. Now: one bordered band, the two
  tracks as a joined segmented control with the sentence beside them, the
  status chips on one baseline underneath. 146px to 96px. Both shared
  components (`TrackTabs`, `StatusTiles`) are restyled BY CONTEXT from
  `index.css` and neither file was edited — the tickets list renders
  `StatusTiles` too.
- **The money strip is 184px tall instead of 116px, with all four figures
  intact.** The four icon tiles went (a generic clock / hammer / check /
  banknote said nothing the label did not). The sentence under each
  figure was REWRITTEN, not trimmed: each states the consequence the
  label does not — "Money committed, not yet earned", "Lands when the
  work finishes" — because a second line that only rephrases the heading
  earns one line's worth. Labels, values, request counts and the unpriced
  counts all still render.
- **The wave-1 chip fix was re-verified, not assumed.** Clicking each
  track still lists rows (13 on Quote & price, 5 on Chargeable work),
  "All" stays lit on both, a chip still narrows (3 rows) and clears back
  to 13.

**Not done, on purpose:** the nine ticket status tiles on
`/tickets/chargeable` are untouched. They are the Tickets page's control
— `variant="tickets-page"` renders the same ones — so thinning them
changes a page nobody complained about, and "Waiting for the manager"
does not survive the one-line treatment in the measured 118px column.
`/tickets/chargeable` gets the compact strip and nothing else.

### Done — Sprint 189 §§1–4 (chat 1 of 3): the four layout changes

Frontend only. Plan §2.1, items 2–5. No backend file was touched and no
backend test was run, because nothing on the server changed.

- **§1 — Department and Work Type sit under Preferred Date.** The Details
  card's dates grid is two columns and held three cells, so the fourth
  slot — directly under Preferred Date — rendered as blank surface while
  the same two fields lived in a collapsed card in the right-hand aside,
  two clicks and a scroll away from every other field of their kind. The
  card is gone; the values are in the cell, with an Edit trigger beside
  them and the form opening below the grid — the Sprint 177 §2 shape the
  deadline cell one row to the left already uses. Provider-only, exactly
  as the aside card was: measured on a CUSTOMER_USER, neither the cell
  nor the department name appears anywhere in the page text. The locked-
  by-invoice case keeps both of its sentences (which invoice, and the
  reverse-relabel-rebill way out) inline in the cell instead of behind a
  dead Edit button. Customer Contacts takes the freed height: its scroll
  box goes 190px → 248px, the collapsed card header (46px) plus the 12px
  column gap. Nothing else about that panel changed.
- **§2 — the workflow buttons are the primary action, on BOTH pages.**
  Measured before and after on the same DOM, at 1440px: the Ticket
  page's `.status-btn` goes 42px/13px → 53px/15px, the Extra Work page's
  `.btn-sm` workflow buttons go 30px/12px → 48px/15px. Sizing and weight
  only — every colour token and hover rule is the one the button already
  carried, so a Reject button does not turn green by growing. The
  correction actions behind "show correction actions" and the
  Confirm/Cancel pair inside the override reason box stay small on
  purpose; enlarging them would flatten the hierarchy the disclosure
  exists to create. A long translated label wraps (69px) instead of
  overflowing.
- **§3 — Location and Customer, prominent on the Ticket page.** A new
  always-visible card, second on the right rail, values at 22px between
  the header description's 17px and the h1's 36px. It is an ADDED
  display: the Ticket details card still carries both rows, unchanged.
  It renders UNCONDITIONALLY — deliberately not tied to `canConvertTicket`
  or any other gate. A room label keeps its building underneath it.
- **§4 — right column order.** Measured in the DOM as
  `side-card-workflow` → `ticket-place-card` → `side-card-assignment` →
  `responsible-managers-section` → `ticket-schedule-card` →
  `side-card-details`. The Workflow card was at the BOTTOM, below five
  cards an operator had to scroll past to reach the only control that
  moves the ticket. The card itself is unchanged; only its position is.

**Gates.** `tsc --noEmit -p tsconfig.app.json` clean over 293 project
files (a bare `tsc --noEmit` scans NOTHING here — `tsconfig.json` is
`"files": []` with two project references, so it prints a vacuous pass);
`eslint .` exactly 44 (42 errors, 2 warnings), baseline held, no new
`eslint-disable`; `vite build` OK. nl/en `extra_work.json` both 553 keys,
zero asymmetry, one key added (`detail.labels_edit`).

**Measured, not eyeballed.** 1440x1000, real data from a throwaway
seeded database, both pages: `document.scrollWidth` equals
`clientWidth` (1440) — zero horizontal overflow — with the Details card
at 741px, the Extra Work workflow card at 371px, the ticket rail at
361px, and no element in either page overflowing its own box, including
a deliberately long department name and a 56-character room label.
### Done — W1-C: four figures, and the track tabs stopped emptying the list

Branch `feat/ew-gap-closing` (the Extra Work gap-closing plan,
`docs/planning/ew-gap-closing-plan.md` §2.4 and its chip fix). Ran as one
of THREE parallel Claude Code chats on that one branch, on a disjoint
file set. The `## NOW` header above still names `feat/sprint-188`, and
all three chats left it alone for the same reason: rewriting one shared
paragraph from three chats at once conflicts three ways over prose. It
is the closing chat's job, and it is the one thing in this file still
owed.

- **Picking a track no longer empties the list.** `switchTrack` reset the
  status filter to the string `"ALL"`, and the All tile is `""`.
  `StatusFilter` is a bare `string`, so nothing caught it: choosing
  Quote & price or Chargeable work set a value no chip owns, every row
  was filtered out and NO tile lit up. Picking a track now selects All,
  which is what the owner asked for and what the line's own comment
  always said it did.
- **A money strip on the Extra Work list and on Chargeable work.** Four
  figures, each with a sentence under it saying what it means: quoted and
  not yet started, in progress, done in this billing month, and — of that
  — the part already invoiced. The fourth is labelled as a share of the
  third ("Daarvan al gefactureerd"), because four numbers that look
  independent invite somebody to add them up.
- **One aggregate, not a sum of the page.** New
  `GET /api/extra-work/financial-summary/`
  (`backend/extra_work/views_financials.py`). Two queries, constant in
  the row count, pinned by `assertNumQueries` at two different sizes. It
  computes NO money and NO classification of its own: amounts come from
  `reports.dimensions._amounts_for_state` (the server mirror of
  `rowAmounts()`), and which bucket a row lands in comes from
  `extra_work.billing`'s `is_billable` / `billing_month`. W1-B's billing
  cutoff widens `is_earned`; because this endpoint calls it rather than
  restating it, that widening arrives here by itself.
- **Provider management only.** STAFF and CUSTOMER_USER get 403, and the
  strip renders nothing for them. A customer's own money already has a
  customer-facing surface; a provider's commercial roll-up is not
  something to hand them by accident.
- **Zero still is not "unpriced".** Each figure carries how many of its
  requests nobody has priced; a figure where that is ALL of them renders
  an em dash instead of EUR 0,00. The sums are untouched — an unpriced
  row contributes zero, because zero is what it contributes.
- **`is_priced` has one definition again.** Sprint 188's three-EXISTS
  expression moved out of `ExtraWorkRequestViewSet.get_queryset` into
  `views_financials.is_priced_expression`, which the list now imports.
  It also gained its first backend test, in the new module.

### Done — Sprint 188: zero is a price, and a customer is not an employer

- **An unpriced job no longer reads EUR 0,00.** Zero is a LEGAL price —
  free work and a goodwill line are ordinary business — so "nobody has
  priced this" and "this costs nothing" must not render the same. A new
  `is_priced`, annotated once per page with three EXISTS subqueries that
  mirror `active_priced_lines`' resolution order exactly, drives an em
  dash on the list, the phone card and the detail header. DISPLAY ONLY:
  `rowAmounts()` is untouched and stays the one billing-total rule, and
  sums still count an unpriced row as zero.
- **The legacy `/pricing-items/` surface can no longer overwrite an
  approved quote.** Sprint 187 gave the proposal route a writer for the
  three quote columns without noticing that surface already had one,
  reading a different line set: posting one legacy row replaced an
  approved EUR 484.00 quote with whatever was posted, with no override
  recorded and no history row. Now 400 `legacy_pricing_locked_by_proposal`
  on all three mutation paths; an EW with no approved proposal still
  prices the legacy way.
- **"Memberships" was telling the owner something untrue.** A customer's
  contact person showed "Companies: Osius Demo" under "…this user belongs
  to". That entry is not a membership and cannot be —
  `CompanyUserMembership` is COMPANY_ADMIN-only by construction — it is
  `company_ids_for`'s CUSTOMER_USER branch resolving `customer.company`,
  the provider that SERVES them. Meanwhile STAFF showed nothing about
  their employer, because that helper has no STAFF branch.
  `scoping.employing_company_names_for` now answers "who employs this
  person" in ONE place (the union 187B worked out for the Employees
  directory), `UserDetailSerializer` gains `employed_by`, and the card
  says what it means. `company_ids_for` itself is UNCHANGED — it is the
  tenant-scoping helper behind `/auth/me`, and editing its CUSTOMER_USER
  branch would be an H-1/H-2 change, not a copy fix.
- **Users can be filtered by customer**, with the
  `customer__company_id__in=scope_company_ids` clause that stops the
  filter becoming an existence oracle for another tenant's customer ids.
- **Platform admins stopped vanishing from the Users list.** The company
  filter auto-selected on a one-company install AND disabled its own
  dropdown, which pinned it on with no way back — and because the filter
  drops rows holding no membership in the chosen company (deliberate, and
  the owner confirmed he wants it), every SUPER_ADMIN disappeared
  permanently.
- **A recurring job could silently lose its category on save.**
  `effectiveCategoryChoice` collapses a selection that does not belong to
  the chosen customer — deliberate — but could not tell that from "the
  list I check against has not arrived yet", and PATCH honoured the
  resulting null. The keys are now OMITTED until both lists are loaded,
  the rule the crew payload a few lines below already stated.
- **Screen fixes:** the chargeable-work table fits its track (MEASURED:
  1230px -> 978px inside a 978px track, in three steps — density, then
  wrapping, then 6px off each side of the cell padding; the tickets page
  measured immediately after was unchanged); the billing address is named
  on both the customer overview and the building overview, where it is
  shown per linked customer because a building's own address is the work
  site and not the invoice address.

### Done — Sprint 187C: the repair command had to be safe to trust

Verification of 187 found defects in the one thing the owner runs by hand.

- An Extra Work already carried by an ISSUED or SENT invoice is now
  SKIPPED and named, not silently re-priced. The invoice's own amounts
  were never at risk — they are snapshotted into `InvoiceLine` — but the
  Extra Work would have started displaying a number that disagreed with
  the invoice that billed it, with nothing recording the change.
  `label_validation.py` already freezes an EW's labels at ISSUED for the
  same reason.
- "Wrote N row(s)" counted candidates minus every failure, mixing two
  populations: one good write beside one compute failure printed
  "Wrote 0" after having written a row — and that number is what the
  owner reads to decide whether the run worked.
- Change detection compared the total alone, so a row with the right
  total and a wrong subtotal/VAT split was reported "already correct".
- `--include-nonzero` could write 0.00 over a real total.
- Three comments in 187 did not hold and were corrected, including one
  claiming a state was "no longer reachable" that the same commit's own
  `_ParentAdvanceBlocked` arm creates.
- A test had gone vacuous: the new gates forced `can_direct_publish`
  False for every EW its fixture builds, so it stayed green with the
  permission restored. It now opens the other gates and carries a control
  that fails without the fix.

### Done — Sprint 187B: which company employs a person

Ran in a PARALLEL Claude Code chat, on an explicitly disjoint file set,
and merged with zero conflicts — the pattern is worth keeping.

- `?company=` on `/api/users/` and `/api/employees/`, intersected INSIDE
  the caller's own company set so it narrows and can never widen (H-1/H-2),
  with a cross-tenant test on each and a control beside it so an
  implementation that returned nothing for every value could not pass.
- The Users list names WHICH companies a person belongs to instead of
  only how many, bounded to two names plus "+N more".
- The Employees directory gains a company column. Its exact-key-set
  privacy assertion was amended deliberately, kept exact rather than
  weakened to a subset check, with the reasoning recorded in the test:
  a provider company name is not customer linkage.


### Done — Sprint 187: finishing what was half-wired

Every item was already half-built: a function with no caller, an
endpoint with no button, a flag mirroring half its own gates, a filter
the list understood and the counts did not.

- **§1 Quoted extra work no longer reads EUR 0,00.**
  `ExtraWorkRequest.subtotal_amount` / `vat_amount` / `total_amount` are
  the quote cache every list, widget, report KPI, CSV export and detail
  header reads, and only the LEGACY `/pricing-items/` views ever wrote
  them. Work priced through a Proposal — approved, ticket spawned — read
  zero everywhere. `final_amounts.recompute_quoted_totals` writes them
  now, frozen at proposal approval in
  `_advance_parent_on_customer_decision`, which is the one helper every
  approving route reaches (customer decision, provider override,
  direct-publish, Sprint 6B auto-start). It uses the **ordered**
  `line.quantity`, never `billable_quantity` — a quote is what was
  ordered, a final amount is what was delivered — and that distinction
  is pinned by a test that re-measures an hourly line and asserts the
  quote does NOT move. Deliberately NOT inside a never-fail
  `try/except`: the ticket-approval freeze is, because a freeze failure
  must not break a ticket transition; a silent failure here is how a EUR
  484 job comes to invoice at EUR 0.00. Existing rows are repaired by
  `manage.py backfill_quoted_totals` (`--dry-run`, `--company`,
  `--include-nonzero`), which the OWNER runs.
- **§2a The order trap is closed.** "Prepare proposal" was offered on a
  REQUESTED parent and the create endpoint admitted one, but `can_send`
  requires UNDER_REVIEW — so an operator built a whole quote and found
  no Send button, and no "Publish directly" either (it derives from
  `can_send`). Creating a proposal IS starting the review, so it now
  advances the parent through the NORMAL `apply_transition`: the
  `_advance_parent_on_send` bypass exists only because the
  PRICING_PROPOSED leg enforces `pricing_line_items_required` against
  the legacy line model, and REQUESTED -> UNDER_REVIEW does not touch
  that precondition. History row in the same transaction,
  `is_override=False`. An actor who may not advance still gets their
  proposal, with the reason on `parent_advance_blocked` — and the
  builder now renders a DISABLED Send with the reason beside it instead
  of rendering nothing.
- **§2b A sent quote can be withdrawn and a draft discarded.**
  `can_cancel` had been advertised for DRAFT and SENT since the endpoint
  shipped and read by nothing. Frontend only. The SENT leg is coerced to
  an override and requires a reason, so the dialog collects one and
  disables Confirm until it is typed; the DRAFT leg is a plain
  transition. `ConfirmDialog` rendered unconditionally, ref-driven.
- **§2c A saved proposal line can be edited.** `updateProposalLine` and
  its PATCH endpoint both existed with zero importers, so correcting one
  price meant deleting the line and retyping every field. The composer
  is now one component for add and edit rather than a second form.
- **§2d The workflow card says where the decision went.** At
  PRICING_PROPOSED with an open proposal it rendered nothing and
  explained nothing. Purely additive — the `!hasOpenProposal` guard is
  load-bearing and untouched; only a sentence was added.
- **§3 "Publish directly" no longer fails by default.**
  `can_direct_publish` mirrored two of the endpoint's four gates. The
  two it missed are the two that fail in a DEFAULT deployment: the
  dedicated dangerous grant `provider.extra_work.quote_override_start`
  (OFF by default; the generic B6 key does NOT satisfy it — H-11) and
  `request_intent == REQUEST_QUOTE`. Reporting authority, not granting
  it: the endpoint's own checks are untouched.
- **§4 "Algemeen" is gone from the English UI.** Four call sites printed
  the auto-seeded label raw — and two of them printed it TWICE, not once
  as reported: the invoice list, the customer-labels DELETE DIALOG (one
  screen away from a row that was already correct), both classifiers on
  the recurring-job detail, and both levels of the reports department
  tree. Seven raw renders in four files, all through
  `customerLabelName`.
- **§5 The ticket chips count what the rows count.** Sprint 185 taught
  the work-category dropdown to the LIST only; `/tickets/stats/` never
  learned it. Third appearance of this exact defect (work-type dash,
  customer "25", now category), so the existing `customer` block was
  copied rather than re-derived, tolerant int parse and all. Plus a
  "Not yet categorised" option, emitting the `category__isnull` lookup
  the backend has offered since the catalog shipped.
- **§6a Invoices say which company issued them.** Numbering is gapless
  per company per YEAR, so two rows legitimately both read `2026-0001`.
  `company_name` on the provider serializer only —
  `CustomerInvoiceSerializer` is deliberately untouched.
- **§6b Service pickers are scoped to the right company** at the three
  call sites where that was genuinely the cause: the convert-to-extra-
  work dialog, the customer pricing page's service dropdown (Sprint 142
  narrowed its CATEGORIES and stopped there), and the recurring-job
  form's category picker. The other three reported sites had a
  different cause and were left alone — see the report.
- **§6c Contracts admin has a company column and filter.** Frontend
  only; `company_name` was already in every row and `?company=` already
  accepted. `BuildingsAdminPage`'s pattern verbatim, table and phone
  card list changed together.
- **§7** Two Customer-pricing dialogs announced `Delete {{name}}` /
  `Move {{count}} row(s)` to screen readers — the `aria-label` IS the
  accessible name on a `role="dialog"`. And the "Nothing to invoice"
  heading, translated in both bundles since Sprint 183 and rendered by
  nothing, is rendered.
- **§8** This file: two `## NEXT` headings merged into the one ordered
  queue the second already claimed to be, the truncated sentence Sprint
  175 left mid-word repaired, and NOW brought forward three sprints.

### Deliberately NOT done

- **The Users / Employees company work.** Named in the prompt as the one
  thing to leave; it is a larger job than §6a–§6c and is in `## NEXT`.
- **No `## SHIPPED` line was written.** This file's own rule is that a
  PR cannot cite its own number, so the entry for this chain is appended
  by the first commit of the NEXT branch. Inventing one here is exactly
  the "do not invent status" trap.


### Done — W1-B (Extra Work gap closing, wave 1, chat 2 of 3)

**Branch:** `feat/ew-gap-closing`. Three chats in parallel on disjoint
files (W1-A layout, W1-B this, W1-C financial totals) — see
`docs/planning/ew-gap-closing-plan.md`, which is the contract.

- **The billing cutoff (plan item 14).** `extra_work.billing.is_earned`
  had exactly one arm — the spawned operational ticket is CLOSED — and
  CLOSED is reachable only through APPROVED, which is reachable only
  through WAITING_CUSTOMER_APPROVAL. So work the customer had not
  answered yet was not merely dated wrong, it was **out of the billing
  pool entirely**, and `invoice_date` could not rescue it because
  `invoice_date` only relocates work that is already earned. The owner's
  case: billing date 30 August, work done 29 August, approval 4
  September — August found nothing, September billed August's work.
  There is now a SECOND arm: earned when the ticket is at
  WAITING_CUSTOMER_APPROVAL with `sent_for_approval_at` stamped.
  **WAITING_MANAGER_REVIEW qualifies under neither arm** and must not be
  added to one — that state is staff saying "done" with nobody having
  checked, and billing it would bill unverified work.
- **The cutoff comparison is not re-implemented.** The rule is "sent for
  approval on or before the customer's cutoff", and the cutoff is
  supplied by WHEN the invoice run fires: `run_daily_invoice_run` runs on
  `schedule.is_billing_day` and asks for this period OR EARLIER. Work
  sent for approval after that day does not exist yet when the run reads
  the pool. No second copy of `invoicing/schedule.py` to drift from.
- **One definition of earned, not two.** `reports.dimensions
  ._classify_extra_work` re-tested `ticket.status == CLOSED` itself; it
  now calls `is_earned`. A new `earned_at()` is the single anchor that
  `billing_month`, `InvoiceLine.performed_on` and the report's
  "Completed At" column all read, so the month, the invoice line and the
  report cannot disagree about which date they mean.
- **The customer is told, before they decide.** A `BillingCutoffNotice`
  component on the customer's Meldingen and Facturen pages, and the same
  three sentences in the approval-request e-mail — plain Dutch, nl
  primary, en in lockstep. Not dismissible and not in Settings: a notice
  the reader can un-see, or has to go looking for, is not a notice.
- **The SLA engine now talks to somebody (plan §2.7).** It has run every
  five minutes over every live ticket since Sprint 7 with real
  business-hours arithmetic and notified NOBODY, and all nine
  `NotificationEventType` members were event-driven — "nothing happened
  and it should have" was an empty category. `sla/warnings.py` is that
  category: three warnings (approval due before the cutoff; manager
  review past target; planned work not started), each with ONE
  escalation hop at a second threshold, on the existing five-minute
  beat, through the existing `send_logged_email`, with the existing
  tenant-scoped rosters. Repeat suppression is a query against the
  `NotificationLog` rows the sweep itself wrote, not a "did we run?"
  flag.
- **Extra Work has a clock.** `reconcile_sla_states` iterates `Ticket`
  only, so an approved-and-planned Extra Work with no spawned ticket had
  no clock at all. The not-started sweep covers it, anchored on
  `provider_planned_date` (what the provider committed to) and never on
  the customer's `preferred_date` (what they asked for).

### Deliberately NOT done — W1-B

- **No credit-note or reversal mechanism.** One already exists and it
  already answers "the customer rejects after we billed": a SENT invoice
  is immutable, and reversal releases the work via
  `invoice__reversed_by__isnull=True` in `invoicing/selectors.py`.
- **No persisted SLA status column on Extra Work.** That needs a field
  on `extra_work/models.py`, which wave 2 owns. The warning sweep
  computes the Extra Work clock per tick instead.
- **No in-app (bell) rows for the three warnings** — e-mail only this
  round. The in-app feed is a second surface with its own enum and its
  own read/unread lifecycle; adding it is a follow-up, not a detail.


### Done — W2-B (Extra Work detail page, wave 2, chat B of 4)

Frontend only. Four fixes on
[frontend/src/pages/ExtraWorkDetailPage.tsx](../../frontend/src/pages/ExtraWorkDetailPage.tsx)
plus the `.ew-*` block of `index.css`. Every layout claim below is a
number read off the live DOM at 1440px, against the same page built from
the branch point in a second worktree — not an impression.

- **The label editor opens where the labels are.** Department and Work
  Type display on the RIGHT of the details grid (Sprint 189 put them
  there). Pressing "Edit labels" opened the two dropdowns on the far
  LEFT, below the whole grid: measured at x=307 w=695 while the fields
  they edit sit at x=662 w=341. The editor now opens inside that cell —
  x=662 w=341 — stacked rather than in a row, which is the only thing
  Sprint 189's "does not fit in a half-width cell" was actually about.
- **Customer contacts moved into the Details card.** It was a COLLAPSED
  card in the far-right rail, three columns from the request it
  describes. The lower half of the card is now two columns: the
  description / billing month / override / routing text on the left
  (379px), contacts on the right (300px). `:only-child` spans the left
  block across both columns for the roles that may not see contacts at
  all (it is SUPER_ADMIN / COMPANY_ADMIN only, mirroring a backend 403),
  so a building manager does not get a half-width card with dead space.
  The list scrolls inside itself — measured with 12 contacts:
  scrollHeight 992 inside a 300px box, panel capped at 350px, page
  horizontal overflow 0.
- **Messages went from 741px to 1128px.** It was the left column of a
  2fr/1fr row whose right column held contacts. With contacts gone the
  rail held at most one collapsed 46px header, so the row was deleted;
  Preview joined the full-width collapsed stack (People, Requested
  services) where it reads as one of a set.
- **Colour on the workflow buttons, and an ORDER to go with it.** Every
  status button was `.btn-secondary` — "Start review" and "Cancel
  request" identical outlined boxes, one under the other. The forward
  action is now filled green and every cancelling or rejecting action is
  `.btn-danger`, both existing tokens. Measuring it also caught two
  things nobody had asked about: the backend hands
  `allowed_next_statuses` in enum order, so **Cancel rendered ABOVE
  Start review**; and at CUSTOMER_APPROVED with no spawned tickets,
  "Mark in progress" and "Retry scheduling work" both came out green.
  Forward now sorts first and cancel last, and while a repair is
  pending the repair keeps the emphasis.

### Deliberately NOT done — W2-B

- **No i18n keys added.** The moved contacts panel reuses the three keys
  the card it replaces already used, so nl/en stay in lockstep with no
  edit.
- **The provider-override Approve/Reject pair and the customer-side
  Reject were NOT measured live**, only read. No seed row reaches a
  PRICING_PROPOSED-with-override-and-no-open-proposal state, and the
  synthetic response built to force one threw in the page, so it would
  have been a measurement of a broken render. Their classes are static
  ternaries in source.


### Done — Sprint 191 §2.5 (wave 3, chat I of 5): the photo pool

Staff uploads land internal. Nothing a worker uploads reaches the customer
until a provider manager releases it, and phase (before / after) is a label
that decides nothing.

- **`TicketAttachment.visibility`** — INTERNAL / CUSTOMER, its own column
  beside `is_hidden`, not a reuse of it. `is_hidden` is moderation (hides a
  row from everyone below provider management, STAFF included);
  `visibility` is the customer wall (INTERNAL still shows the worker their
  own photo). Migration `0027` backfills every existing row to the level it
  was already being served at — `is_hidden` rows to INTERNAL, everything
  else to CUSTOMER — so no file changed audience when the column arrived.
- **The wall is enforced on BOTH read paths.** The list queryset and the
  download endpoint refuse the same rows for a customer-side caller; a wall
  on one of them only would have been decorative, because the download URL
  is the second way to reach a file.
- **The default is resolved in one place** (`_default_visibility`): a
  customer's own upload is CUSTOMER (hiding it from the uploader is a bug,
  not a privacy win), a provider-side upload is CUSTOMER only when the work
  carries `staff_uploads_customer_visible`, and everything else is
  INTERNAL. Only provider management may name a `visibility` at upload;
  STAFF sending one gets a 400 `visibility_forbidden`, mirroring the
  existing `is_hidden` rule.
- **Promote is one PATCH**, `…/attachments/<id>/visibility/`, provider
  management only. The role gate answers 403 before any object lookup, then
  the ticket is resolved through `scope_tickets_for` — so a manager of
  another tenant gets a 404 and cannot promote across a tenant boundary,
  and an attachment id belonging to another ticket 404s on this ticket's
  URL. Releasing a row that `is_hidden` or an internal note would still
  hide is refused (400 `attachment_visibility_conflict`) rather than
  producing a pill that lies.
- **The per-work setting** `Ticket.staff_uploads_customer_visible` (PA/SA
  only, terminal-ticket guard, one AuditLog row) changes only what happens
  next: it never retro-promotes what is already stored.
- **Completion evidence is untouched, and that was verified rather than
  assumed.** Both gates —
  `state_machine._ticket_has_visible_attachment` and the per-slot gate in
  `views_staff_assignments.py` — count `is_hidden=False` rows and neither
  reads `visibility`. Pinned three ways in
  `tickets/tests/test_sprint191_attachment_visibility.py`: an INTERNAL
  photo still satisfies the ticket-level helper, a hidden one still does
  not, and a slot completes through the real API on an INTERNAL photo with
  a blank note.
- **Frontend:** `AttachmentThumb` carries the state and the action. A
  provider-side viewer sees an "Alleen intern" / "Zichtbaar voor klant"
  pill; provider management additionally gets the release/withdraw control.
  A customer sees neither — every file they are served is customer-visible
  by construction, so a pill saying so is noise.

### Deliberately NOT done — Sprint 191 §2.5

- **No toggle in the ticket page for the per-work setting.** The API, the
  detail payload and the Django admin field are in;
  `frontend/src/pages/TicketDetailPage.tsx` belongs to another chat this
  wave, so the switch has no mount point yet. Chat E owns the placement.
- **Extra Work has no photo pool of its own.** Photos live on the spawned
  operational ticket, which is what this sprint hardened;
  `backend/extra_work/**` was not touched.

### Done — W3-F (Extra Work detail page + the planning screen, wave 3, chat F of 2)

Frontend only. `ExtraWorkDetailPage.tsx`, three new components under
`components/extra-work/`, the planning types in `api/types.ts`, the
`.ew-*` block of `index.css`, and the bulk action on the list page.
Every layout number below is read off the live DOM at 1440px against the
same page built from the branch point in a second worktree.

- **Department and Work Type are edited IN PLACE.** Pressing Edit used to
  open a form under the two values — two full-width dropdowns and a
  button row — which pushed Description, the billing month, the override
  and Routing down the page by 169px every time. There is no form now:
  the two values become selects in the slots they already occupy, and
  Save / Cancel stand where the Edit button stood. **Measured, closed vs
  open: Description 477 / 477, Billing month 533 / 533, Routing 725 /
  725, card height 610 / 610.** Before the change the same four numbers
  were 477 / 646, 533 / 702, 725 / 894, 638 / 807. Held by three things
  together: identical outer markup in both states, one pinned height
  shared by `.ew-label-value` and `.ew-label-inline-select`, and a save
  error that goes to a TOAST rather than an inline banner — an error
  banner in that cell would push the page down at the worst moment.
- **Customer contacts reads as a column of the card, not a box on top of
  it.** Its heading sat 13px below the Description heading it was meant
  to line up with, because the panel carried 12px of its own padding
  inside a filled, bordered box. Padding, background and border are
  gone; a rule down its left edge says "different column" without saying
  "different card", and the heading wears the same `muted small` class as
  every other label in that half. **Description 477, contacts heading
  477.** The wave-2 scroll behaviour is intact: 12 contacts, 712px of
  content inside a 300px box, panel 322px, page overflow 0.
- **The planning layer has a screen.** W2-D shipped `plan/` and
  `bulk-plan/` complete and tested and nothing called them, so from the
  owner's chair the feature did not exist. There is now a Plan work
  action on the detail page opening a modal with budget hours, OUR
  committed window (labelled as ours, with the customer's requested date
  and deadline shown beside it read-only), one row per assigned person,
  and the two completion switches. The button says PLAN AND START.
  Measured 560x779 at 1440px and at 1280px, page overflow 0 at both.
- **The overrun warns and does not block, and that was measured, not
  asserted.** With 6 budget hours and 9 distributed the warning renders
  and `submit disabled` reads FALSE. A real submit went through at 200
  with `content-type: application/json`, the dialog closed, and the
  summary rendered the budget, the distribution, the window, the per-
  person hours and the overrun.
- **A real bug the measurement caught.** The first build tracked both
  completion switches with ONE "touched" flag, so flipping "photo
  required" also sent `completion_notes_required: false`. Harmless on
  the single-work dialog, where both switches are seeded from the row —
  and the reference system's exact defect on the BULK dialog, where they
  start at false because the selected works disagree and there is
  nothing to seed from. One flip would have cleared the notes flag on
  every work in the batch. Now one flag per switch, verified on the
  wire: touching only the photo switch sends
  `{"requests":[...],"budget_hours":"4","file_upload_required":true}`
  and no notes key at all.
- **Bulk plan** is on the Extra Work list's edit-mode toolbar. 560x672,
  page overflow 0 at 1440 and 1280, the selected works listed in a
  bounded box, Confirm disabled only when there is literally nothing to
  write.

### Deliberately NOT done — W3-F

- **No per-work values in the bulk table.** `POST /extra-work/bulk-plan/`
  takes ONE payload and applies it to every id; a grid of per-work values
  would need either an API change (forbidden this sprint) or N separate
  calls, which would throw away the endpoint's all-or-nothing property.
  The dialog says plainly that the values go to every selected work.
- **No planned hours in the bulk dialog.** The server refuses hours for
  anybody not assigned to EACH selected work, so one shared distribution
  is only valid when the same crew is on every job; offering the field
  would produce a 400 that reads as a bug in the dialog. Hours are
  planned per work.
- **No client-side block on the overrun anywhere**, by instruction and on
  the evidence: the reference system's own `validateTotalHours()` is a
  complete function that is never called, under the comment "// Hours
  validation removed per user request".

### Done — W4-R: a wage per person, dated, and nobody's business but two roles'

W3-H shipped ONE deployment-wide hourly rate and said so out loud: the only
knob until a real per-person rate was designed. This is that design, plus the
privacy rule that has to come with it.

- **The rate is per person AND dated.** New model
  `reports.models.EmployeeHourlyRate` — one row per (employee, company,
  `valid_from`), open-ended and superseded rather than edited. The rate that
  costs an hour is the row in force **on the day of that hour**: latest
  `valid_from` at or before it, ties by `-id`, the identical resolution shape
  `extra_work.pricing.resolve_price` and `timesheets.ContractHours` already
  use. Additive migration `reports/0001_initial.py` — the first model in an app
  that until now was views over other apps' tables.
- **A RAISE NEVER RE-PRICES THE PAST, and that is the decision the sprint
  turned on.** Two ways to get it: snapshot the rate onto the hour entry, or
  version the rate and resolve it by date. **Time-ranged, because the snapshot
  is not available to us** — it needs a money column on `TimeEntry`, which is a
  `timesheets` model, and that module holds no wage by rule and by a test that
  walks its every file. The seam W3-H named
  (`reports.labour_cost.resolve_hourly_rate`) exists so the answer never has to
  reach into that app, and it did not. `valid_from` alone with no `valid_to`: a
  closed range can leave a GAP, and a gap silently falls through to the
  deployment rate — a different number arrived at by nobody's decision.
- **Cost is now computed per person per day, not over one summed total.**
  `labour_cost()` takes `HourSegment(employee_id, on_date, weighted_hours)`
  and prices each at its own rate; `RateBook` loads a whole crew's history in
  ONE query. A job that ran across a raise costs January's days at January's
  rate and May's at May's — 8h at EUR 20.00 plus 8h at EUR 31.75 is EUR 414.00,
  not 16h at either.
- **The global rate is still the FALLBACK** for anyone with no personal rate,
  and when neither exists every cost figure is still NULL. **A zero is never
  printed** — "we do not know" and "it was free" stay different claims.
- **Partial knowledge is not a total.** A crew where one person has no rate and
  there is no fallback produces NO `hours_cost` and NO `total_cost` — plus
  `unrated_weighted_hours`, so the absence carries its reason instead of being
  a blank. A figure covering two thirds of a job is the number an operator
  reads as the job's cost and acts on.
- **A wage is personal data, and the line is enforced at the API.** New
  `IsLabourRateManager` + `reports/labour_rate_scope.py`: SUPER_ADMIN and
  COMPANY_ADMIN (own company only). **BUILDING_MANAGER is refused** — every
  verb, every URL — even though they are admitted to every OTHER reports
  surface by `IsRevenueReportConsumer`; STAFF are refused including for their
  own rate; every customer-side role always. Tested by calling the real URLs
  as each of the five roles, not by checking a screen.
- **The back door is closed and here is the choice.** A one-person job's
  labour cost divided by its hours IS that person's rate. There is no partial
  answer that survives that division, so a BUILDING_MANAGER gets **no cost
  block at all** on the hours panel — `cost: null`, on every job, whatever the
  crew size, whether the rate is personal or global, and including a job they
  worked themselves. They see their own hours, as they do everywhere else, and
  no money beside them.
- **BUDGET HOURS STILL NEVER FEEDS COST.** W3-H's test (multiply the budget by
  a hundred, assert every cost figure byte-identical) still passes, and gained
  a twin that does the same with a personal rate in play — the per-person path
  added a second lookup and the budget had to stay no nearer it than before.
- **The timesheets purity test still passes, and was TIGHTENED.** It scanned
  for `hourly_rate` / `labour_cost` / `labor_cost`; `EmployeeHourlyRate`
  lowercases to `employeehourlyrate`, which none of those catch, so a rate
  lookup could have been added to `timesheets/` and passed the old test. It
  cannot now.
- **Editing history is allowed and is a different thing from a raise.** PATCH
  and DELETE re-price the period the edited row covers, deliberately: somebody
  who typed 24.50 for 25.40 has to be able to fix it. What the model prevents
  is a rate change moving the past as a SIDE EFFECT of an ordinary raise. Every
  write lands on the `AuditLog` with a before/after diff (the model joins the
  full CRUD trio in `audit/signals.py`).
- **The UI says where each number lives** (plan decision 12). New "Uurtarieven"
  tab on the Uren admin page — that route already admits SA / CA only, which is
  exactly the endpoint's admit set — leading with a sentence stating that hours
  are recorded in the hours module, which holds no amounts, and that the rate
  lives in reporting. Current rate per person, the full dated history, and a
  form whose hint says a raise is a NEW row from a NEW date. "No rate set"
  renders as words, never as EUR 0,00.


## Historical — Sprint 181

**Branch:** `feat/sprint-181`, cut from the INTEGRATED Sprint 180 (see
the note under Sprint 180 below — `origin/feat/sprint-180-merged` did
not exist when this branch was cut).

### Done — Sprint 181: one fact, one place

- **§1 The ticket is the authority for operational state.** An Extra
  Work carried its own status AND its spawned ticket carried one, and
  `IN_PROGRESS -> COMPLETED` was documented as "SYSTEM auto ... **or
  provider manual**". That last clause is how rows on crmtest came to
  read COMPLETED against a ticket that was still OPEN. Once an Extra
  Work HAS a live ticket, the two forward operational pairs (exactly
  `SYSTEM_AUTO_TRANSITIONS`) are system-only: no role can drive them,
  `allowed_next_statuses` withdraws the buttons, and the endpoint
  answers `operational_status_follows_ticket` rather than a generic
  permission error. `COMPLETED -> IN_PROGRESS` (edge recovery, reason
  required), `IN_PROGRESS -> CANCELLED`, and EVERY manual transition on
  a ticketless Extra Work are deliberately untouched. One predicate
  (`_operational_status_is_derived`), two callers, no second copy.
- **§1 The Work started track shows the TICKET's status**, on the list
  and in the CSV export, with no pricing-stage status surviving into
  that track at all. The detail page adds a "Work status" cell carrying
  the ticket's status and its number, so nobody wonders where the value
  came from or why the workflow buttons no longer move it.
- **§1b Ticket numbers no longer run together.** Three renderers for one
  fact (list table, mobile card, detail card) became one
  `SpawnedTicketLinks`, with a real text separator instead of a margin,
  and a bound: `max` links then `+N`.
- **§2 Nine status chips became four, twice.** Quote & price shows
  commercial states (Awaiting pricing · With the customer · Rejected ·
  Cancelled); Work started shows TICKET states (Open · In progress ·
  Awaiting customer · Finished). Each track offers only what can be
  non-zero within it. The duplicate status `<select>` is gone.
- **§2b `Customer approved` split.** `Price approved` where the customer
  accepted the quote, `Work approved` where they accepted the finished
  work. The other three bare "Approved" strings are listed in NEXT.
- **§3 `reconcile_extra_work_status`.** Reports by default, repairs only
  with `--repair`, prints the table either way, and NEVER writes a
  status `ALLOWED_TRANSITIONS` forbids — where the derived value is not
  reachable the row is reported and left alone. On crmtest: 8 repairable
  (COMPLETED against an unfinished ticket) and 8 report-only (the mild
  IN_PROGRESS-against-an-untouched-ticket shape).
- **§4 SLA separated from workflow status**, and `Historical` removed
  from the UI entirely — filter option, badge and tooltip. A UI removal
  only; the backend constant and `sla_backfill` are untouched.
- **§5 Chargeable work.** A tickets sub-page at `/tickets/chargeable`
  (the same list component with `?is_extra_work=true` pinned), a nav
  entry, and ONE name used by the nav, the sub-page title, the row pill
  and the Extra Work list's second tab. EN "Chargeable work" / NL
  "Meerwerk" — **the owner is invited to veto the word**.
- **§7 `active-filter-chip` / `active-filter-clear` defined.** They were
  used five times in `DashboardPage.tsx` and defined in no CSS file,
  which is why the ticket list read "...is hiddenShow all". The sweep
  that should have caught them is now a COMMITTED script
  (`frontend/scripts/check-css-classes.mjs`) rather than something run
  by hand — see NEXT for the 35 other undefined classes it found.
- **§8 The Work Plan's undated work has a place.** `undated_entries` on
  the work-plan payload (same builder, bound and truncation flag as its
  two siblings) and a "Not planned yet" lane above the week, replacing
  the one muted sentence that stood for 43 of 70 live tickets. Each
  ticket row carries a one-click "Plan for today".

### Not done — Sprint 181 §6

**§6 (splitting the invoice TARGET from the split-granularity) was not
started.** It is a data-model change plus a faithful data migration plus
a rewrite of `generate_draft_invoices`' grouping, under an explicit
"nobody's behaviour changes" requirement, and starting it without room
to finish and test it would have been worse than deferring it. Carried
into NEXT with the analysis done.

### Gates

`extra_work` (whole app) + `tickets.tests.test_state_machine` ran
isolated in this worktree: **1035 tests, all passing** (the run also
reported one ERROR, which was a module name I mistyped on the command
line — `tickets.tests.test_filters` does not exist — not a test).
Re-run afterwards for the surfaces that name covers:
`tickets.tests.test_sprint181_chargeable_and_undated` (new),
`test_sprint179a_work_plan`, `test_sprint170_agenda_scope`,
`test_m6_ticket_customer_filter`, `test_inactive_filtering`. `invoicing`, `reports`, `timesheets`,
`buildings`, `accounts`, `planned_work`, `contracts` NOT run and not
touched. `makemigrations --dry-run --check` clean — **no new migrations
this sprint**. Frontend: tsc clean, eslint 44 (42 errors, 2 warnings),
build OK, i18n key gate clean, nl/en lockstep clean.

### Done — Sprint 180 (integrated, recorded here late)

**This file had NO Sprint 180 entry.** Five agents worked five branches
and each handed its checklist lines to the integrator; the integration
commit did not fold them in, so a whole sprint was missing. Recorded
from the commit subjects rather than from the five reports, so treat the
detail as thinner than usual:

- Batch 1 (`84d26e5`) — Extra Work rows: the two-track split on the
  canonical `Ticket.extra_work_request` FK, the spawned-ticket link on
  the list and detail serializers, a pre-existing `started_before_plan`
  N+1 killed, `billed_to` (BUILDING | CUSTOMER), the dashboard
  billing-period money bug, and `BuildingType` + `ManagedUnit`
  registered for audit.
- Batch 2 (`060a3ad`, `ba083fb`) — ticket lifecycle: approval closes the
  ticket; the ticket list says what it is.
- Batch 3 (`346f0ff`) — reports: "this building, last month".
- Batch 4 (`8572ff3`) — invoice PDF.
- Batch 5 (`adf9e4e`, `3eae4bf`, `9134eff`, `dc2192c`) — chrome: ten
  dead class names, the week grid, two fields, an e2e assertion.

**Sprint 180 was never pushed as `feat/sprint-180-merged`.** The
integration exists only as the local `integ180` branch, and it was
missing `feat/sprint-180-tickets`' final commit; `feat/sprint-181`
starts with that merge so all five batch tips are ancestors.

### History — Sprint 179A

**Branch:** `feat/sprint-179a`, cut from `feat/sprint-178` (`56c0740`).
Still ONE chain, one PR — #153 -> ... -> #179 are not one PR per sprint.

Sprint 179 was split across two agents on two branches, both cut from
`56c0740` and neither rebased onto the other. **Agent A owns this file**;
Agent B hands its checklist lines to web-Claude at integration, so the
Sprint 179B entries below this line are expected to arrive later rather
than to be missing.

### Done — Sprint 179A: the Work Plan, seventh round

- **The §12B week-placement rule, implemented — all four points.** It
  had been recorded as DECIDED and unimplemented for five sprints. The
  rule now lives ONCE, in `backend/tickets/work_plan.py`, as pure
  functions over dates: a `Job` (planned window, due date, state) that
  both sources are flattened onto, so a dated ticket slot and an extra
  work request are placed by the same code. A job appears in the week
  its planned window covers, whatever its status; a STARTED job also
  appears in the current week; a job past its deadline and unfinished
  also appears in the current week, marked overdue; untouched future
  work appears only in its own week plus an Upcoming list. Rules 2 and 3
  add to the CURRENT week only, which is what makes point 4 fall out in
  both directions. **A card outside its planned week says why** — a red
  "Overdue — due <date>" or an amber "Started early — planned for
  <date>" marker, carrying the planned date, so the operator who meets
  the same job in two weeks can tell them apart.
- **Extra work in the week view.** Sprint 168 recorded this as blocked
  on "giving extra work a schedule … a product decision, not a screen".
  That decision has since been made and shipped: Sprint 173 §4 gave
  extra work a planned WINDOW (`preferred_date` -> `planned_end_date`)
  and a `deadline`, and Sprint 157 §2 gave it people
  (`ExtraWorkAssignment`). So no new product decision was needed — the
  week view now reads both. Extra work is **assignment-driven**: a
  request with nobody on it is not yet anybody's work and does not
  appear.
- **Server-side counts.** New composite endpoint
  `GET /api/tickets/work-plan/?week=YYYY-Www[&scope=company]` returns
  the week's cards, an Overdue list, an Upcoming list, and every count
  as a `COUNT(*)` over the scoped queryset. The chips used to be
  computed in the browser over whatever had been fetched. Because the
  rule is now expressed twice — Python for placement, querysets for the
  counts — `WorkPlanRuleParityTests` asserts the two agree over a
  fixture built to hit every branch. All three lists are bounded
  (300 / 100 / 100) and the response says out loud when a bound bit.
- **STAFF can see the extra work they are assigned to, and only that.**
  `scope_extra_work_for` still returns `.none()` for STAFF — the
  post-2026-05-20 privacy fix is NOT reopened. What is new is the shape
  `Ticket.extra_work_origin` already uses: a caller-scoped read of the
  worker's own assignment rows through a narrow OPERATIONAL serializer
  (title, building, customer name, planned window, deadline, urgency,
  status). No commercial field exists on it, and the test pins its key
  set exactly plus a named list of the fields that must never appear.
- **The idempotent demo seeder.** `seed_demo_data` now seeds eight dated
  ticket slots and five assigned extra-work requests for Ahmet, across
  several days, three buildings and every state the chips count.
  Running it twice creates nothing new — and it **re-stamps its dates
  relative to today on every run**, which is the difference between an
  idempotent seeder and a frozen one: a fixture pinned to the day it was
  first seeded shows an empty week a fortnight later.
- **The owner's acceptance test, as data and as a test.** An extra work
  assigned to Ahmet as a WORKER, past its deadline, appears as overdue
  in Ahmet's Work Plan. Pinned twice: once against a directly-written
  assignment, and once through the real
  `POST /api/extra-work/bulk-assign/` so the eligibility gate and this
  read are proven to line up.
- **The BUILDING_MANAGER scope was already covered — and is now
  reachable.** Sprint 170 §1 admitted all three provider-management
  roles to `?scope=company` (`is_provider_management_role` includes
  BUILDING_MANAGER), so no new scoping path was written. But the page
  never asked for it: `agendaShowsTeamWeek` listed only SA and CA, so a
  manager reached a personal view that is as empty for them as it was
  for an admin — the exact defect Sprint 170 fixed one role short of.
  One-line fix, and the manager's assigned-tickets table is kept BELOW
  the week rather than replaced by it (two different questions).

### Two changes of behaviour worth flagging

- **The completion buttons now appear only on your OWN slot.** In team
  scope an admin previously got "Mark done" on a worker's card; a
  mis-click there writes a false completion record against somebody
  else's name. `can_complete` is now the server's answer.
- **The raw Status select is gone from the Work Plan filters.** It
  listed untranslated enum strings and duplicated what the chips say in
  normalised form. The chips (Total / Overdue / Open / In progress /
  Completed / Can't complete) replace it, and a new "Kind of work"
  filter separates tickets from extra work.

## Historical — Sprint 178

**Branch:** `feat/sprint-178`, cut from `feat/sprint-177` (`feb4ead`).

### Done — Sprint 178

- **§1 the Catalogs area — SIXTH round, done.** `/admin/catalogs`
  gathers hour types, work types, contract types, building types and
  managed units behind five tabs, each rendering the SAME component its
  old page renders, so the old entry points all still work and the two
  cannot drift. Services stay a LINK (they carry prices, VAT and
  per-customer rates — not a name-and-active-flag catalog).
  Plus the mechanism's proof: a per-company `BuildingType` on the
  `HourType` shape, an optional `Building.building_type` (SET_NULL), the
  building form, the building detail, and **a filter on the buildings
  list**. Measured: created "Health building", tagged ONE of two
  buildings, filtering returns exactly that one. 20 tests.
  **Cost of the next catalog: six files** (model, migration, serializer,
  views, urls, a ~70-line `CatalogTab` wrapper). `standardSetUrl` is now
  optional so a bespoke catalog needs no fake standard set. NOT
  generalised: the serializer + views are still ~290 near-identical
  lines per catalog; a generic `CatalogViewSet` would collapse them to
  ~30 and is a real refactor across five live catalogs. **Adding a TYPE
  needs no deployment** — there is a test named for it.
- **§2 the four reports — SIXTH round, done.** Employee hours by
  building / weekly / by extra work, and a ticket report whose duration
  comes from `TicketStatusHistory` (first terminal arrival, so a reopen
  is a new episode not a longer one). Cards opening modals, no new nav
  children, CSV + PDF through `reports/exports.py`, `assertNumQueries`
  on each — measured rather than hardcoded, asserting the count does not
  GROW with the data. Provider-only; STAFF and CUSTOMER_* get 403.
  **What each finds on the dev database:** by building 3 groups /
  125.75h, weekly 2 weeks / 125.75h, **by extra work 0 jobs / 0.00h**,
  tickets 18 rows / 4 finished / 0 days average. The empty one is
  correct and says so in words — nothing is tagged to a job yet.
- **§4 the source's two gaps.** Editable from the entries EDIT path now,
  using the same `listHourSources` the week setup uses (no backend
  change needed — the fields were already writable and no screen ever
  sent them). And CONTRACT / OTHER are offered as type-only sources with
  a null id, closing a display that supported a value nothing could set.
  `OTHER` stays the default for untouched rows.
  **Recommendation, as asked: `ContractHours` should NOT carry a
  source** — its rows are contract hours by definition, and a column
  that can hold one value is not information. Stated, not built.
  Also corrects Sprint 177's report: it claimed contract hours "all have
  source CONTRACT". They have no `source_type` column at all.

### Found, NOT fixed — 30 pre-existing raw-key bugs

Tightening the i18n gate (it now searches only the FIRST declared
namespace, which is what i18next does — there is no `fallbackNS` here)
and running it over the whole frontend for the first time surfaced **30
keys that render literally today**, none of them from this sprint:

    UnifiedTimeline.tsx                        6
    BuildingManagerCustomerContactsPage.tsx    7
    BuildingManagerCustomersPage.tsx           3
    BuildingManagerCustomerDetailPage.tsx      4
    ChangeDiff.tsx                             1
    CustomerInvoicesPage.tsx                   1
    CustomerReportsPage.tsx                    1
    (plus repeats of the same keys)

Verified real: `t("loading")` in a component declaring only `common`,
where `loading` lives in `dashboard.json`. Eight files this sprint did
not otherwise touch — that deserves its own round rather than a
footnote, so it is recorded here rather than done quietly.

### NOT done in Sprint 178 — §3 and §5

- **§3 the Work Plan.** Not reached. Verified along the way that ONE
  part of it already exists: the BUILDING_MANAGER / admin team view
  through `scope_tickets_for` landed in Sprint 170 §1
  (`?scope=company` on `my-slots/`), so that sub-item needs nothing.
  Still outstanding: the §12B week-placement rule (points 2-4), extra
  work in the week view, server-side counts, the idempotent seeder, and
  the owner's acceptance test.
- **§5 the typography sweep.** Not started. The prompt named it the item
  to drop if something must be dropped, and something had to be.

The reason, plainly: §1 and §2 were each a full-stack feature with a
migration or four new endpoints, and §4 turned out to need a nullable id
threaded through the week grid. §3 is a fifth feature of the same size.
Starting it without finishing it would have left the branch half-done,
which is worse than leaving it whole and saying so.

## Historical — Sprint 177

**Branch:** `feat/sprint-177`, cut from `feat/sprint-176` (`4da3bf2`).

### Done — Sprint 177

- **§1 the planned window's four cases.** A range with one end missing
  is not a range: with an end and no start the page printed
  `— – 16 Aug 2026`, an em dash standing in for the absent start. Four
  cases now enumerated in `frontend/src/lib/plannedWindow.ts` (both /
  start only / `Until <date>` / em dash), measured on four rows built
  for the purpose. In `lib/` because §6's Work Plan cards will render
  the same window and a second copy would drift.
- **§2 the Edit dates button was invisible — because of a missing
  class.** Sprint 176 wrote `btn-secondary btn-sm` without the base
  `btn`, so it inherited no button styling at all; two more buttons in
  the same component had the same defect. Now `btn btn-secondary
  btn-sm` + a 13px Pencil (the contact-permissions / employees house
  pattern), 150x30, and MOVED into the deadline cell beside the value
  it edits (measured same-line) instead of floating under the grid.
- **§3 the right column, settled.** Sprint 176's `1fr 1fr` stretch is
  gone; `align-self: start` lets the column end where its cards end.
  Measured at 1024/1280/1440: collapsed [50,50] column 112; expanded
  [240,240] EQUAL, column 492; contacts body shows 190px of 608px so it
  SCROLLS rather than stretching the column; 0 page overflow in every
  state.
- **§7 the hour source — verified first, then the real gap closed.**
  Most of this section already existed and was NOT rebuilt: the Source
  column (173), the filter (174), the approval tab grouped by source
  with per-group counts (`actualBySource`, 174 §2) and
  approve-everything-for-this-employee-this-week (`approvableByEmployee`,
  174 §2). The genuine gap was that NOTHING FILLED the pair — scanned
  every writer: read, filtered, serialised, accepted as explicit input,
  never derived. New `GET /api/reports/hour-sources/` (the list
  direction of `resolve_sources`, in `reports/` because `timesheets`
  imports neither module) plus an optional Job picker in the week
  setup, each chosen job seeding its own row. 13 tests; verified by
  clicking. **A per-source APPROVE action is deliberately still not
  built** — `TimeEntry` has no status field, so the rows with varied
  sources are worked hours nothing approves, and the approvable rows
  are contract hours that all have source CONTRACT. Making it real
  means giving TimeEntry an approval lifecycle: an owner decision.
- **§9 both small items.** The forecast's "Current monthly" now carries
  "As at today (<date>), on the revision now in force" via a new
  optional `hint` on `Tile`. And the stale `section-title` entries are
  DELETED — Sprint 173 §6 defined it at `index.css:333` and 39 files
  use it.

### NOT done in Sprint 177 — carried whole, not started

**§4 (the Catalogs area), §5 (the four reports) and §6 (the Work Plan
week-placement rule) were not reached, for the sixth round.** They keep
their full detail in `## NEXT`. **§8 (the typography sweep) was also
not started.**

The honest reason, stated plainly because the pattern is now the
problem: §1–§3 were fixing defects this chain shipped, and §7 turned
out to need a new cross-module endpoint plus a week-grid row-identity
change rather than the small wiring its description implied. Each of
§4/§5/§6 is a multi-hour full-stack feature; starting one without
finishing it would have left the branch half-done, which is worse than
leaving it untouched and saying so.

**`## NEXT` is therefore NOT empty**, contrary to §11's target. What
remains is exactly §4, §5, §6 and §8 — nothing new was added to it.

## Historical — Sprint 176

### Done — Sprint 176

- **§1a raw translation keys, and the gate that could not see them.**
  Sprint 175 rendered `detail.field_department` and
  `detail.field_work_type` literally on screen; neither key existed in
  either bundle. Lockstep passes on a key missing from BOTH bundles,
  which is the same blind spot that hid `employees.open_account` in
  Sprint 156 — twice now. The read-only card that carried them is gone
  (§1b), and `frontend/scripts/check-i18n-keys.mjs` now asserts every
  `t("...")` literal resolves in a namespace the file declares.
  It caught five genuine missing keys while §3 was being written.
- **§1b the duplicate Department & work type card.** Sprint 175 added a
  READ-ONLY one above the EDITABLE Sprint 128 card. The read-only copy
  is deleted; the editable one moved into the right column behind a
  `collapsible` prop on the component itself (wrapping would nest a
  card in a card). Relabel endpoint, invoice-lock state and error codes
  all intact.
- **§2 the layout the owner redrew.** People on this request is a
  full-width collapsed row below Messages —
  `ExtraWorkAssignmentCard` gained a `bare` prop that renders its body
  without its own card shell, which is the nesting problem solved
  rather than avoided. The right column is Customer contacts +
  Department & work type sharing the height (`grid-template-rows: 1fr
  1fr`). Measured: Messages 488 / right column 488 / **gap 0** and zero
  overflow at 1024, 1280 and 1440.
  **Flagged, not hidden:** filling a 488px column with two collapsed
  cards means ~188px of empty space under each header. The alternative
  is opening both by default — a one-word change, left as the owner's
  call because the sketch says collapsed.
- **§3 the deadline's editing surfaces.** The EW ViewSet has no update
  mixin by design, so both dates were write-once on the create form:
  nothing anywhere could change a deadline after the fact, which is
  precisely when deadlines get agreed. Added, in the shape of the
  existing `labels` action rather than a general PATCH:
  - `PATCH /api/extra-work/<id>/dates/` — set or clear either date, and
    an Edit affordance on the detail page's Details card that uses it.
  - `POST /api/extra-work/bulk-dates/` — the same two dates across a
    selection, all-or-nothing, behind the list's existing edit gate.
    A blank field is OMITTED from the payload, never sent as null, so a
    bulk deadline cannot wipe a planned end date nobody touched.
  - Both write through ONE helper (`extra_work/dates.py`) so the two
    paths cannot drift on what makes a window valid.
  - **The DECISION, so the owner can reverse it in a sentence: the
    deadline is provider-only.** The customer keeps `preferred_date`
    (their wish, shown beside the deadline field on the provider's
    editor); the deadline is what turns a row red and what an operator
    is measured against, so a customer who could set it could make the
    provider look late by typing a date. Enforced in three places — the
    create serializer (400), the dates endpoint and the bulk endpoint
    (403 `deadline_provider_only`).
  - 18 tests, including the Sprint 174 §0 render test on the endpoint
    that carries the fields, "absent leaves it alone", "null clears it",
    the all-or-nothing rollback, and H-1 (a cross-tenant id answers
    identically to one that does not exist).

### NOT done in Sprint 176 — carried whole, not started

§4 (the Catalogs area), §5 (the four reports) and §6 (the Work Plan
week-placement rule) were NOT reached. They keep their full detail in
`## NEXT` below. This is the fifth round they have been carried, and
the honest reason is that §1, §2 and §3 consumed the sprint: §1 was
fixing defects this chain shipped, and §3 turned out to need three new
endpoints rather than a form field, because nothing in the system could
edit an extra work after creation.

## Historical — Sprint 175

**Branch:** `feat/sprint-175`, cut from `feat/sprint-174` (`1fe1489`).

### Done — Sprint 175

- **§1 the Extra Work detail redesign — the item owed for three
  rounds.** Details and Workflow keep their content and stay open on
  the top row, untouched. Messages moved into a SECOND two-column row;
  the right column takes Customer contacts (new, collapsed, with its
  count), Department & work type (new, collapsed), People on this
  request (moved), and Preview (new, collapsed — the proposal PDF was a
  button inside Workflow). Requested services and Pricing proposal stay
  full width beneath, both collapsed. Nothing removed.
  Measured — the right column is SHORTER than Messages at every width,
  which is the question the owner asked:
  1024 488 vs 389 · 1280 488 vs 373 · 1440 488 vs 338 · overflow 0.
- **§3 the counts.** `.mywork-chip-count` had no left margin, so
  "Draft0". It has 6px now and its weight drops 800 -> 700 to match the
  label beside it.
- **§5's CSS debt.** The six classes the sweep flagged for two sprints
  are defined, because §1 rebuilt the files carrying them. **The sweep
  is clean.**

### Two honest notes on §1

- **People on this request renders OPEN, not collapsed.** It is an
  existing self-contained card component and wrapping it would nest a
  card in a card. The right column is still shorter than Messages at
  every width, so the acceptance criterion holds — but it is not
  collapsed as the sketch drew it.
- **Preview renders only where a proposal exists.** On a request
  without one there is no PDF to preview and an empty card would be
  furniture.

### NOT done

Four items, none partially built:

- **§2 the deadline's editing surfaces** — editable after creation
  (2a), in the list's bulk edit (2b), and provider-only with the API
  refusing it from customer-side roles (2c). §2c is a DECISION awaiting
  the owner either way, so it is recorded in NEXT with its reasoning
  intact.
- **§3's typography sweep** beyond the counts. The count fix landed;
  the wider "too large and bold" pass over the touched pages did not.
- **§4a the Catalogs area**, **§4b the four reports**, **§4c the Work
  Plan** — a third sprint carrying these.

### Gates

`test extra_work` isolated in this worktree — the only app whose
BACKEND this sprint changed (§1 and §3 are frontend and CSS).
`timesheets`, `reports`, `buildings` and `tickets` were NOT run and
nothing in them was touched. `makemigrations --dry-run --check` clean —
no new migrations. Frontend: tsc clean, eslint **44 (42 errors, 2
warnings)**, build OK, i18n in lockstep, **undefined-CSS-class sweep
clean**.

**CC updates `## NOW` / `## NEXT` / `## SHIPPED` for a sprint as part
of that sprint's own commit(s)** — not in a later docs-only pass — so
this file always reflects where we actually are.

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

## Historical — Sprint 166

**Branch:** `feat/sprint-166`, cut from `feat/sprint-165` (`18c2d72`).
It is the single branch being merged — #153 → … → #166 are ONE chain,
one PR, not one per sprint.

**Deployed to crmtest at the owner's instruction** (the prompt said not
to; the owner overrode it in the same session).

### The standard this sprint was held to, and why it was fair

Two Sprint 165 items were reported as delivered and could not be reached
by a user: a reporting endpoint with no screen, and a page with no link.
An endpoint returning 401 proves a route exists, not that a feature
does. Every item below was reached by CLICKING from the sidebar, and the
report says which entry.

### Per item

- **§1 fill rule — DONE, third statement and the first correct one.**
  The rule is about WHERE a row came from, not WHEN. Both earlier
  attempts reached for timing because the row carried no way to tell the
  wizard's rows from the operator's — `added` is true for both. The row
  is now MARKED at creation (`manual: true`) and the fill skips it.
  Verified in the failing order: add a type FIRST, then fill →
  `7,7,7,"",7,7`, the added row untouched.
- **§2 modal size — DONE.** `width: min(96vw, 1180px)` plus a
  min-height; it had a cap and no floor, so it collapsed to its
  content. 1024 → 983x741, 1280/1440 → 1180x741, page overflow 0.
- **§3 sideways scroll — DIAGNOSED and fixed.** Two rounds "measured as
  fixed" because they measured only the OUTER modal. All four levels
  with the grid POPULATED found it: modal 0, inner 0, **gridWrap
  258/61/61**, table 0. Day cells 64px → 54px takes 70px out across
  seven days: gridWrap now **195/0/0** — nothing scrolls at 1280 or
  1440, and at 1024 the container scrolls, which is the documented
  fallback. The modal itself never scrolled.
- **§4 hours comparison — HAS A SCREEN.** Sidebar → **Contract vs
  worked** (under Reports) → `/reports/hours-comparison`. Period
  selector, a row per building with contracted / worked / difference,
  the sign carried by an under/over/on-target tag, a grand total, and
  the per-worker breakdown expandable on the WORKED side. The page
  states the asymmetry instead of hiding it.
- **§5 customer contracts link — DONE.** Sidebar → Customers → a
  customer → **Contracten** in the submenu →
  `/admin/customers/3/contracts`. The route has existed since Sprint 162
  with no way to reach it.

### The §5 sweep

66 routes checked by trailing segment (a prefix match would not have
caught the very defect §5 names). Three with no in-app link:

  * `/admin/customers/:id/quote-requests` — a genuine orphan, and
    almost certainly superseded: the IA note of 2026-06-25 merged
    Meldingen and Offerteaanvragen into Extra Work as filter chips. Left
    unlinked deliberately rather than re-exposed against that decision;
    it should probably be DELETED, which is a decision not a fix.
  * `/invite/accept` and `/password/reset/confirm` — reached from
    emailed links. Correct as they are.

---












## NEXT

Single ordered queue. Sprint 188 §docs re-verified this section **item by
item against the code** instead of carrying it forward on trust, because
most of it had quietly become false: the Catalogs area, the four reports,
the Work Plan's week-placement rule, the building-type catalog, the
invoice target/granularity split, the contract-type catalog screen, the
worker hour reports and the beat-wired month-end invoice run were all
still listed as open, and all of them had shipped.

<!-- How this pass was done, so the next one can repeat it rather than
     trust it: each carried item was checked against the code that would
     have to exist if it had shipped (a component, a serializer field, a
     beat entry, a gate's measured output), not against a sprint report.
     Anything that could not be settled that way is kept below and
     labelled as not re-verified, rather than being quietly dropped. -->

### Open — verified still open

1. **The Extra Work list's "Total value" sums the loaded set, not the
   filtered view.** It reads every request the page fetched, minus the
   cancelled ones, while the row count beside it counts what survived
   the search / chip / category / planned filters — so the two disagree
   the moment anybody filters. W2-C moved it out of a KPI card and onto
   the list toolbar and deliberately left the arithmetic alone, because
   that sprint was about layout and quietly changing a money number in
   one is how a screen loses its owner's trust. The fix is
   `sumRows(visibleRows)` from `lib/billing.ts` — the one rule, already
   imported by that page — plus a label that says which set it means.
2. **The INSTANT / cart route never writes the quote cache.**
   `instant_tickets.py` sets `CUSTOMER_APPROVED` directly with no
   Proposal, and nothing on that path writes `subtotal_amount` /
   `vat_amount` / `total_amount`. Sprint 188's `is_priced` makes such a
   row read as an em dash rather than EUR 0,00, so it no longer LIES —
   but the columns are still unwritten, and `_earned_amounts` falls back
   to `total_amount`. Measured on crmtest during 188: zero rows are
   currently at risk (every affected row either carries a final amount or
   is genuinely unpriced), so this is a gap to close deliberately, not a
   fire.

3. **`select_for_update` on the unbilled pool.** Two concurrent invoice
   runs could both claim the same extra work. Deferred from the invoicing
   sprints; no report of it happening, and the nightly job is the only
   scheduled writer.

4. **The invoice preview does not share the real renderer's layout.** It
   answers "what would be billed" correctly; it just is not the PDF.

5. **`/admin/customers/:id/quote-requests` — delete it or re-expose it.**
   Three references remain in the frontend and nothing routes to it. A
   decision, not a build.

6. **The typography sweep**, owed since Sprint 175 and dropped or
   partially done several times since. Genuine outliers only; the
   building and customer detail pages are the house scale.

7. **An undated extra work cannot be planned in one action** from the
   Work Plan — it has to be given dates first, elsewhere.

8. **Extra work with nobody assigned never reaches the Work Plan.** The
   week view is built from assignments, so unassigned work is invisible
   exactly when someone needs to notice it.

9. **The Work Plan demo seeder** does not add scheduled tickets and extra
   work, so a fresh dev database shows an empty week.

10. **The forecast's "Current Monthly" needs an as-of-today label.**
   Without it the number reads as a full-month figure.

11. **The three remaining bare "Approved" strings** — the status word
    without saying approved BY WHOM, which is the distinction the owner
    has drawn twice: on a ticket it means the customer accepted the WORK;
    on an extra work it means they accepted the PRICE.

12. **20 undefined CSS class names.** CLOSED as a defect by Sprint 187's
    verification — every one is paired with a defined companion class or
    is a no-op hook, and the count is byte-identical to the base commit.
    Listed here only so the next sweep does not re-open it.

### Decisions the owner owes — no build until he answers

- **Who may set a deadline on an extra work** — provider only, or the
  customer too? The editing surfaces exist; the policy does not.
- **Whether a SUPER_ADMIN should stay visible when the Users list is
  filtered by company.** Sprint 188 kept the current behaviour (they drop
  out, because a platform admin holds no company membership) and pinned
  it with a test. Reversible in one line.
- **The invoice email trigger.** The code is written and unfired; the
  owner said it is not needed yet.

### Standing milestones

- **Production deployment.** `crmtest` runs the production compose stack,
  but production itself is not deployed. Open since the beginning.
- **A frontend component/unit test runner.** There is none. Adding one is
  its own sprint and needs the owner's sign-off (CLAUDE.md §8); Playwright
  e2e stays the only frontend test surface until then.
- **The `osius.*` provider permission namespace** is technical-debt
  naming. Renaming it needs a dedicated sprint.
- **The deprecated `Customer` staff-visibility fields and the
  single-building anchor FKs** (`Customer.building`, `Contact.building`)
  are still the runtime read source, kept nullable for back-compat.
  Nothing new builds on them; the read-switch is unscheduled.

### Candidate sprints, none committed

Raised but not decided. Listed so they are not re-discovered as new.

- **Mobile UI polish.** The phone card lists exist everywhere the tables
  do, but they have never had a pass of their own.
- **Refactoring.** `accounts/` carries four overlapping permission
  modules (CLAUDE.md §7), all live and all imported.
- **A light / advanced mode split**, so an operator who wants six fields
  is not shown sixty.
- **Contract planning — the reference system's full-screen week grid.**
- **A data-gap analysis against the reference system**: which data it
  holds that this system cannot represent, EXCLUDING the things already
  considered and declined below.

### Considered and DECLINED — do not propose again

Rooms, quality inspections, project planning, products/stock, and
"continuous extra work". The owner considered each and said no. They are
recorded here so a later analysis does not present them as gaps.

### Not re-verified in this pass

Carried honestly rather than dropped: the per-sprint carry-over sections
that used to fill this queue were retired once their items were checked,
but a handful of narrow notes from Sprints 167–175 (agenda-vs-Work-Plan
analysis, a slot deadline column, the Approval tab's grouped-by-source
half) were not individually re-tested against the code. If one of them
matters, re-derive it from the code rather than from this file.


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
