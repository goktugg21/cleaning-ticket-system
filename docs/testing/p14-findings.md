# P-14 findings — "Everything, end to end" (2026-09-02 → )

The owner's brief: *"Test the system end to end, everything, every
capability, visually, as a person who knows nothing, as different
users. Don't trust the tests we have. Backend, frontend, and between
them."* This file is the sprint's product: every defect, cold-read
failure and drift found, with evidence, sorted S1 → S4. Items marked
**FIXED (P-14)** were small and certain and shipped in this sprint;
everything else is P-15's prioritised input.

Severities (§B4 of the brief): **S1** the stranger's guess was wrong
and the action is destructive or money-related · **S2** wrong and
reversible · **S3** could not tell (the page gave no clue) · **S4**
cosmetic.

Format: page · role · what a stranger sees · severity · the sentence
or change that would fix it.

The checklist this audit ticks off is
[capability-inventory.md](capability-inventory.md).

Sources: (W1) SA + CA width walks · (W2) BM + Bright walks · (W3)
staff + customer walks · (C1) chains 1–3 · (C2) chains 4–7 · (sweep)
the in-sprint part-A/B6 work.

---

## S1

- **P-15: FIXED (§1.1)** — `contracts/state_machine.py` with
  `ALLOWED_TRANSITIONS` (DRAFT→ACTIVE/CANCELLED, ACTIVE→CANCELLED,
  CANCELLED terminal — exactly the UI's own buttons), the
  `/contracts/<id>/transition/` door with the `{detail, code}` refusal
  shape, the serializer's `lifecycle` read-only, the AuditLog diff as
  the history row (zero migrations); the form dialog's lifecycle
  select removed, the detail gains the Cancel door. Pinned in
  `test_p15_lifecycle_machine` (12 tests). ·
  **Contracts · SA/CA · the contract's lifecycle has no state machine
  at all** — `Contract.lifecycle` is a plain writable ChoiceField on
  the detail serializer (`read_only_fields` covers only
  id/contract_no/timestamps), so `PATCH /api/contracts/<id>/
  {"lifecycle": "..."}` performs ANY jump with a 200: a CANCELLED
  contract back to ACTIVE, an ACTIVE one silently to DRAFT (which
  stops its invoicing), no confirm, no history surface, no refusal
  except DRF's `invalid_choice` (EXPIRED is unstorable by
  CheckConstraint). Every other money-adjacent machine (ticket, extra
  work, proposal, invoice) has an explicit ALLOWED_TRANSITIONS guard;
  this one has none. NOT fixed in-sprint — the legal-transition set is
  a design decision inside the frozen contracts model (the owner's
  meeting decides the model; a guard + history + a dedicated
  activate/cancel surface is a P-15 sprint item, top of the list). The
  UI's own buttons drive sensible values, so the exposure is API-level
  and operator-role-gated, not public. (sweep)

- **P-15: FIXED (§1.2)** — the shared toggle reads "Select rows /
  Rijen selecteren" (one label, all seven lists); Delete selected
  carries its WhatHappens ("permanently — invoices already made
  stay"); a contract with invoices is unselectable (the checkbox says
  why) AND the server refuses (`contract_has_invoices`); partial
  failures are named per row. Vocabulary pinned in
  `editModeVocabulary.test.ts`; the server floor in
  `test_p15_lifecycle_machine`. ·
  **Contracts list · SA + CA · the "Edit" pencil is the only door to
  destroying a money-bearing record, and nothing says so** — the
  pencil is an edit-mode toggle whose bulk toolbar contains Delete
  selected, a real per-row `DELETE /api/contracts/{id}/`; the detail
  page deliberately offers NO delete, so the mislabeled toggle is the
  sole path to it. Cold read guessed "edit what? — can't tell"; truth
  is a hidden delete. Fix: rename the toggle ("Select rows…") and a
  WhatHappens line under Delete selected: "Deletes the selected
  contracts permanently — invoices already made stay." (W1)

## S2

- **P-15: RULED + FIXED (§0.2)** — the 0.2 ruling ("only APPROVED
  patterns fill the sheet"): `_agreements_for_week` reads
  `status=APPROVED` beside the flag, pinned in
  `test_p15_approved_fill`; the grid says "No approved pattern yet —
  standard lines are empty" under everyone it skips; fold/road-teach/
  empty-week sentences reworded. ·
  **Hours › Agreed hours · SA/CA · the approval road gates nothing in
  the fill** — `timesheets/fill.py::_agreements_for_week` seeds the
  week grid from `auto_fill=True` and the validity window alone, with
  NO status filter: a DRAFT pattern with "Fills the sheet" on fills
  people's weekly sheets exactly like an Agreed one, so
  Draft → Submitted → Agreed is decoration for the fill. Pinned live
  by C2: pattern 17 (Murat, DRAFT, never saved or approved) wrote
  entry 57 (5.00h) on fill-week — an unapproved draft writes hours
  into reports and closing. Fix: a ruling first — "only APPROVED
  patterns fill the sheet" is one query filter + a pin if the owner
  wants it; the fold and the road teach then change one word.
  (sweep, C2)

- **P-15: FIXED (Part 2)** — MyHoursPage resolves a company (the one
  when there is one; remembered/first with a picker when the scope
  has more than one — the admin Hours page's shape, names read from
  the scoped /companies/) and sends it on fill-week and weeks/status;
  the two silent 400s are gone structurally. ·
  **My hours · STAFF (ahmet, both widths) · the worker is blamed for
  input he never gave** — the page loads, he types nothing, and a red
  banner says "Dat is niet geaccepteerd. Controleer wat u invulde…".
  Cause (response-captured): `POST /api/timesheets/entries/fill-week/`
  and `GET /api/timesheets/weeks/status/` are sent without `company`
  and 400 with "company is required when you belong to more than one
  provider company" — Ahmet's timesheet scope spans companies {1,2}
  via building assignments, and `MyHoursPage.tsx` never sends
  `company`. The contract-hours prefill and the closed-week status
  silently fail every load for any STAFF/BM with a two-company scope;
  hours drive pay and invoices. Fix: MyHoursPage resolves and sends
  `company` (a picker when the scope has more than one, like the
  admin Hours page), and the banner names the missing thing instead
  of blaming the worker. (W3)

- **Meerwerk tracker · KLANTGEBRUIKER (tom) · agreed requests that
  await planning vanish while the counter still counts them** — the
  header chip said "Alles 24" over 19 visible rows; the five missing
  ones were all `display_phase: WAITING_PLANNING`, dropped because
  the page's hardcoded `PHASE_ORDER` array omitted it (the Sprint 126
  exhaustiveness trap: a second local array defeats the compiler).
  **FIXED (P-14)** — PHASE_ORDER now derives from an exhaustive
  `Record<ExtraWorkDisplayPhase, …>` covering WAITING_PLANNING and
  WAITING_MANAGER_CHECK with Dutch group labels; the next new phase
  is a compile error. (W3)

- **P-15: FIXED (Part 2)** — `eligible_users_for_building` stops
  narrowing a BUILDING_MANAGER by `manageable_user_ids_for` (an empty
  set for the role): a BM assigned to the building reads the raw
  building set — exactly what the validator accepts — and an
  unassigned BM reads nothing. Pinned in `test_p15_bm_candidates`
  (picker == admin's answer; what it offers, the write accepts);
  sprint158 eligibility + bulk-assign neighbours green. ·
  **Ticket detail › Assign people · BUILDING_MANAGER · the people
  picker is empty on a ticket he can staff** —
  `GET /tickets/{id}/assignments/candidates/?role=WORKER` returns `[]`
  for a BM while CA/SA get both eligible staff, the same BM's direct
  `POST /staff-assignments/` succeeds, and legacy `/assignable-staff/`
  returns both. The AssignPeopleDialog reads candidates, so the BM's
  assign door renders empty — read and write disagree about
  eligibility (picker ⊂ validator, the Sprint 152.1 §1a defect class).
  Repro ids: ticket 311, users 6/5/12. Fix: give the candidates
  endpoint the same eligibility answer as the validator. (C1)

- **Invoice detail / ticket detail / building detail · ALL roles ·
  three fact links 404 for everyone** — the invoice's "generating
  contract" link, the ticket's recurring-occurrence origin-contract
  link and the building page's contracts-card rows all pointed at
  `/admin/customers/:cid/contracts/:id`, a route that does not exist
  in App.tsx, so every click (including SA's) landed on NotFoundPage.
  **FIXED (P-14)** — all three now point at `/admin/contracts/:id`,
  the routed detail (ContractsRoute even admits BM). (W2)

- **P-15: FIXED (Part 2)** — the header subtitle and the headline
  cards say the scope out loud whenever the period narrows
  ("aantallen in september" beside the tabs and in the subtitle,
  from the existing periodPhrase); no fold needs opening. ·
  **Tickets · all management roles · every count is silently
  this-month-scoped** — headline cards read "OPEN 0 · IN PROGRESS 1"
  and the header "0 total tickets" while 32 open tickets exist; the
  period select sits inside the COLLAPSED Filter fold, and only the
  empty-state line ("Earlier: 32 open — Show all time") tells the
  truth, contradicting the cards above it. W2 saw the same chip-row
  contradiction for BM/Bright ("OPEN 0" over "Earlier: 17 open").
  Fix: print the period on the cards ("Open — September") or beside
  the header; a stranger must not open a fold to learn the numbers
  are month-only. (W1, W2)

- **P-15: FIXED (Part 2)** — `attentionSettled`: the greeting makes
  no claim and the attention card is a skeleton until the probes have
  ANSWERED (success or failure); "nothing needs you right now" can
  no longer render ahead of the data. ·
  **Dashboard · CA · a confident zero renders before data exists** —
  while the attention probes load, the page already asserts "nothing
  needs you right now" (greeting AND card) though the API returns 24
  OPEN tickets and 3 WAITING_MANAGER_REVIEW for his company. Captured
  twice; the slow audit backend widened the window, but the false
  assertion is wrong at any speed. Fix: keep the greeting neutral and
  the card a skeleton until the probes resolve. (W1)

- **Hours › Agreed hours · SA + CA · dead inputs and the one fact
  that matters is off-screen** — the seven day-value boxes render as
  editable inputs but accept nothing until the small "Edit" toggle is
  pressed; and the row's Draft/Submitted/Agreed status — the fact the
  page's own teach line says matters — is a STATUS column scrolled
  off-screen right at 1440. A stranger types into a dead box and
  cannot see which rows are locked. Fix: plain text outside edit
  mode; move STATUS beside VALID. (W1)

- **P-15: FIXED (Part 2)** — a ConfirmDialog stands before the
  DELETE and the WhatHappens pre-read says the consequence ("Removes
  this company's own numbers; the platform standard applies from the
  next check."). ·
  **SLA warnings · SA + CA · "Use the standard values" reads like a
  form reset; it is a server-side DELETE** —
  `DELETE /api/sla/warning-thresholds/{companyId}/` discards the
  company's own numbers, live from the next check. Guessed wrong on
  the cold read. Fix: WhatHappens line ("Removes this company's own
  numbers; the platform standard applies from the next check.") plus
  a confirm. (W1)

- **P-15: FIXED (§1.2)** — the toggle renamed ("Select rows"); the
  page already carried its permanent what-happens explainer under the
  toolbar (Sprint 138's `services-bulk-delete-explainer`: deleting is
  permanent, price-bearing rows are blocked), which is the WhatHappens
  in substance. ·
  **Services · SA + CA · the same "Edit" pencil hides a bulk toolbar
  containing Delete** — per-row `DELETE /api/services/{id}/` with a
  partial-failure report, beside deactivate/move, invisible from the
  label. Catalog rows, not money records, hence S2 not S1. Fix: same
  rename + WhatHappens under bulk delete. (W1)

- **P-15: FIXED (§1.2)** — the bulk action says "Deactivate /
  Deactiveren" (label + confirm title; the bodies already told the
  truth), the toggle "Select rows"; pinned in
  `editModeVocabulary.test.ts` ("a deactivate is never called a
  delete"). ·
  **Customers / buildings / companies lists · SA + CA · the pencil's
  bulk action is wired to a `bulk_delete` key but actually
  DEACTIVATES** — two confusions in one: "Edit" hides it, and
  "delete" overstates it (reversible, SA-only reactivate). Fix: label
  the bulk action "Deactivate", the toggle "Select rows". (W1)

- **People › Employees · BUILDING_MANAGER · an Edit pencil and bulk
  "Assign buildings" on a page whose own subtitle says read-only** —
  the confirm would POST `/api/buildings/bulk-link/`, gated
  `IsSuperAdminOrCompanyAdminForCompany` — a guaranteed 403 for a BM.
  **FIXED (P-14)** — the EditModeToggle now sits behind
  `isProviderAdmin`, the same gate the employment-type pencil already
  used. (W2)

- **Invoices · BUILDING_MANAGER · the page's ONE suggested action
  fails on save** — Start here said "Set B Amsterdam's billing day"
  (plus the per-row link), but the dialog PATCHes
  `/api/customers/{id}/`, a provider-admin-only write — 403 for a BM
  who is otherwise a full invoice operator by design. **FIXED
  (P-14)** — the set-billing-day door is hidden for BM; the sentence
  stays. (W2)

- **Contracts › Types tab · BUILDING_MANAGER · write controls that
  always refuse** — `ContractTypesTab` rendered its add/edit/delete
  controls unconditionally, but the backend gates every contract-type
  write behind `IsContractManager` (BM is READ-ONLY on the whole
  contracts module). A BM saw controls that 403 on press — the
  "control that lies" defect class. **FIXED (P-14)** — the tab mounts
  with the page's existing `canManageContracts` answer and hides the
  write controls. (sweep)

## S3

- **P-15: RULED + FIXED (§0.4)** — the 0.4 ruling: one placement law,
  no exceptions. `job_window`/`with_job_dates` lost the wish legs; the
  wish-only ticket sits in the Not-planned strip wearing `wished_day`
  ("Wished for {date}"); the ladder keeps the wish (`job_wish_window`);
  the two P-1 pins rewritten to assert the strip. ·
  **My schedule / Recurring work board · manager/SA · a spawned
  ticket is still placed by the customer's wish** — P-14 A5 removed
  the wish fallback for EXTRA-WORK rows (a wish is not a plan), but a
  ticket spawned from an extra work with only a `preferred_date` is
  still placed in that day's column through `tickets/job_dates.py`
  (pinned by `test_fe4_honest_dates::
  test_a_customers_wish_is_a_wish_not_a_plan` and `test_p1_honest_
  dates::test_the_wish_behind_a_phantom_is_still_a_wish` — placed,
  captioned `CUSTOMER_WISH`, `has_real_plan=false`). The caption is
  honest, but the same owner ruling read strictly puts these in the
  Not-planned strip too. Needs a ruling before touching it:
  W-PLANTRUTH's "one fact places the board" and P-1's
  captioned-phantom design pull in opposite directions here. (sweep)

- **Agenda · BUILDING_MANAGER · on work-plan failure the board lies
  about loading and offers no way out** — a red "Something unexpected
  happened. Please try again." banner while all seven day columns
  keep saying "Loading the week…" forever, nothing in flight, no
  retry control. The API itself is fine when quiet (200 in ~6.4s;
  a 30s probe renders the full board) — the audit's parallel load
  pushed past the 30s axios budget — but this failure UX is exactly
  what a slow-network user gets. Fix: on work-plan failure, replace
  the day columns' loading text with the error state and give the
  banner a Retry door. (W2)

- **/admin/hours, /admin/hours/agreed, /admin/sla-warnings ·
  BUILDING_MANAGER · deep links were silently dumped on the
  Dashboard** — TimesheetsRoute and SlaWarningsRoute navigated to "/"
  bare while every other guard uses `/?admin_required=ok` and shows
  "This area is for admins only." **FIXED (P-14)** — both guards now
  land with the same admins-only banner. (W2)

- **Agenda › Assigned tickets · BUILDING_MANAGER · the Type column
  printed the raw token `type_report`** — AgendaPage translated
  `create_ticket:type_report` but no `type_*` key existed in either
  locale, so i18next printed the key itself, in BOTH languages.
  **FIXED (P-14)** — the six type labels added to create_ticket.json,
  nl+en in lockstep. (W2)

- **Contracts · BUILDING_MANAGER · Start here orders the reader to do
  something the page will not let them do** — "…is a draft without
  lines — put the first line in." — but a BM is a server-narrowed
  READER; on the detail the add-line door is canManage-only and
  hidden. The banner renders from `stats.start_here` with no
  canManage check. Fix: for !canManage show the descriptive sentence
  without the imperative, or hide the Start-here. (W2)

- **Invoices due rows / invoice detail · BUILDING_MANAGER · doors on
  a page he operates by design bounce him to "admins only"** — the
  due row's whole-row click goes to `/admin/customers/:id/invoices`
  and the invoice detail's building facts link to
  `/admin/buildings/:id`, both AdminRoute surfaces. Fix: for BM send
  the due row to `/invoices?customer=` (a surface they hold) and
  render the building name as plain text unless canAccessAdminArea —
  the pattern the invoice LIST already uses for its customer chip.
  (W2)

- **Agenda · STAFF (ahmet) · the Dutch page's week header read "Aug
  31, 2026 – Sep 6, 2026"** — English month names that never healed
  on first mount: `weekRangeLabel = useMemo(..., [week])` while
  `formatDate` reads `i18n.language` at call time; the first mount
  ran before the profile language applied and the memo never
  recomputed. **FIXED (P-14)** — the locale is a memo dependency now.
  (W3)

- **Settings · customer users · the notification toggles speak
  provider vocabulary** — "Ticket aangemaakt", "Ticketstatus
  gewijzigd", "Ticket toegewezen"… to a customer who only ever sees
  "melding" (§D.2). A customer stranger cannot tell these toggles
  govern the mail about their meldingen. Fix: the shared SettingsPage
  needs customer-worded labels (melding-*) when the viewer is a
  CUSTOMER_USER — same keys, role-picked copy. (W3)

- **Extra work list · SA + CA · the "Edit" pencil gives no clue** —
  truth: edit mode revealing bulk Assign / Set dates / Plan. Nothing
  destructive, but the page says nothing. Fix: "Select rows"/"Bulk
  actions" label, and one fold line ("Edit lets you pick several rows
  and assign, date or plan them at once") — no current fold line
  mentions the bulk toolbar. (W1)

- **Audit logs · SA · the RECORD column mixes `extra_work.
  ExtraWorkRequest#281` with bare Dutch display names** — "Overig",
  "Overeenkomsten", "Contracten", "Facturen", "Algemeen" — no type,
  no id. A stranger cannot tell WHAT record those rows touched, on
  the page whose purpose is investigation. Fix: always print model#id
  beside the display name. (W1)

- **Catalogs › Hour types · SA + CA · "COUNTS AS × 1.50" weighs
  what?** — nothing on this page says (pay? price? reports?). The
  true sentence exists but lives on the Hours page's fold ("the hour
  type weighs reports — never the price"); here, where the multiplier
  is EDITED, it is absent. Fix: one subtitle line under the Hour
  types tab: "The multiplier weighs hours in reports; it never
  changes a price." (W1)

- **Extra work create · API · the derived default intent bypasses
  intent validation** — a provider creating an EW with
  `request_intent` omitted gets `REQUEST_QUOTE` stamped (EW 315, kept
  CANCELLED as evidence) — the very intent `validate_intent_for_cart`
  forbids a provider to choose (400 on explicit send). The preview
  advertises the contradiction: `allowed_intents:
  ["AUTO_START_AFTER_PRICING"]` next to
  `default_intent:"REQUEST_QUOTE"` for the same provider+cart. Fix:
  derive the default through the same validator that judges an
  explicit choice. (C1)

- **P-15: RULED (§0.3)** — when the customer structurally cannot sign
  off, the manager's check IS the sign-off and the screen says so:
  `approved_on_behalf` + `customer_can_decide_online` word the fact
  "Checked by {manager} — counts as approved (this customer cannot
  approve online)" on card and detail (pinned in
  `test_p15_on_behalf_signoff`). The money reaches Invoices as before. ·
  **Extra work / tickets · customer (view_own) · auto-start work on a
  view_own-only building is invisible to the customer, including its
  completion approval and its money** — EW 316 / ticket 345: Tom 404s
  on the EW detail and the ticket detail, the ticket is absent from
  his list, the WAITING_CUSTOMER_APPROVAL step can only be settled by
  a provider override on his behalf, and €408.98 sits in the unbilled
  pool without any customer-side user ever having been able to see
  the job. RBAC works as specified (view_own tier); the product-level
  consequence is the finding — AUTO_START pre-authorisation covers
  *starting*, not *completion sign-off*. Needs an owner ruling on who
  signs off. (C1)

- **Work-plan board · manager · an unstaffed ON_HOLD job is on NO
  lane, including "Geparkeerd"** — `_ticket_parked_q` would match
  ticket 309, but `_ticket_source` gates the whole board on
  `Exists(non-cancelled staff slot)`; 309 has none, so counts.parked
  stays 0 and the P-7 quiet list never shows it. The undated lane
  also excludes ON_HOLD by design, so the job vanishes from the
  entire planning surface (escape routes that DO catch it:
  `/invoices/at-risk/` and `/tickets/?status=ON_HOLD`). Fix: let the
  parked lane admit unstaffed parked jobs, or say where they went.
  (C2)

## S4

- **Invoices · API · refusal shape drift** — an illegal invoice
  transition returns a 400 with a human sentence but NO stable
  `code`, unlike every other machine's `{"detail", "code"}` shape;
  and the ticket status endpoint wraps `detail`/`code` in one-element
  lists. Human sentences do reach the screen through `getApiError`
  (P-8 A3 holds), so this is an API-consistency item. P-15: give the
  invoice refusals codes; unwrap the ticket endpoint's lists. (sweep)

- **Recurring work · API · archive/unarchive are idempotent with no
  refusal** — re-archiving an archived rule answers 200. Harmless,
  recorded for the machine table's completeness. (sweep)

- **Extra work / proposal · API · the plan gate answers before
  pair-legality** — an impossible move (e.g. a CANCELLED proposal →
  SENT) is refused with `plan_requirements_unmet` instead of
  `invalid_transition`: a true sentence, but the wrong FIRST reason.
  Cosmetic at the API level (the move is refused either way). (sweep)

- **Hours (worked) · SA/CA · Start here's name list cannot tell two
  Ahmets apart** — the O4 button prints first names ("Enter hours for
  Ahmet, Ahmet, Mehmet and Smoke" on the dev seed): two people who
  share a first name are indistinguishable, and a system account's
  name leaks into a human sentence. Fix: when two missing people
  share a first name, print the full name for both. (sweep)

- **Hours (worked) · SA/CA · "Open" twice in one Earlier-weeks row**
  — the STATUS badge said "Open" (the state) and the row's action
  button also said "Open" (the verb): one word, two meanings, three
  centimetres apart. **FIXED (P-14)** — the button says "Open week"
  (nl "Week openen"). (sweep)

- **Hours (worked) · SA/CA · the empty week's sentence named a button
  that does not exist** — NL `week_empty_body` said "Druk op *Uren
  invullen*" while the button says "Uren invoeren". **FIXED (P-14)**
  in the A1/A4 i18n pass (both locales now name the button and the
  agreed-hours source). (sweep)

- **Recurring · guide fold · "an end date closes it for good"
  overstated** — C2 proved the behavior: after `PATCH end_date`,
  generation correctly creates nothing new, but an occurrence
  materialized BEYOND the end date before it was set (occ 99 / OPEN
  ticket 348, left in place as evidence) stands untouched; the
  operator cancels it by hand. **FIXED (P-14)** — the fold now says
  new visits stop, existing visits keep their day. The behavior
  itself is recorded, not changed. (C2)

- **Error/loading UX under a slow backend · all roles** — the walk
  storm measured 10–35s first paints (work-plan 18.7–32.8s, EW list
  4.6–9.4s), a bare full-page "Loading…", the EW list's blank pane
  with tab counts stuck at "…" for ~5–10s reading as "there is
  nothing here", and the tickets footer "Showing 0 of 0 tickets"
  while rows still skeleton-load. CAVEAT: measured while a 6007-test
  suite hogged the same CPU; the quiet re-measure shows 0.7–2.3s.
  Filed as UX-under-slowness, not performance: give the EW list a
  loading row, the tickets footer a "Loading…", and see the W2 S3
  no-retry banner for the real failure path. (W1, W2)

- **Agenda · SA + CA · titled "My schedule" while the subtitle admits
  "The whole team's week"** — the title is wrong for management
  roles. Fix: "Team schedule" for SA/CA/BM. (W1)

- **Notifications · SA + CA · English scaffolding around Dutch
  payloads** — known localization gap queued behind the owner's
  migration yes; rows are buttons that mark-read + deep-link but
  carry no visible affordance. Fix: localize payloads; give rows a
  chevron. (W1)

- **Customers · SA + CA · RELATIONSHIP and STATUS both print
  "Active"** — indistinguishable words for lifecycle vs is_active.
  Fix: lifecycle words ("Customer / Prospect / Former") in
  RELATIONSHIP. (W1)

- **People › Users vs Employees tabs · SA + CA · same names on both
  tabs, no sentence dividing the labour** — Users = sign-in accounts
  & access, Employees = HR facts; ROLE vs ACCESS ROLE likewise
  unexplained. Fix: one subtitle sentence per tab. (W1)

- **Extra work list · SA + CA · "Price and send" only navigates** —
  the row's strongest verb pair prices nothing itself; it links to
  the detail where that happens. The pre-read belongs on the detail,
  not a surprise navigation. (W1)

- **Dashboard · SA · three numbers that don't reconcile on sight** —
  greeting "71 things need you today", OPEN WORK 76, attention rows
  summing 53 (with "Show all 7"). Fix: make the greeting count the
  attention list it sits above. (W1)

- **CA sidebar · "Hours" and "My hours" sit adjacent with no hint**
  that one is the company grid and the other his personal week. Fix:
  "My own hours" or a divider label. (W1)

- **Contracts · all roles · money tile reads "across 1 active
  contracts"** — plural with count 1. Fix: the i18n plural form. (W2)

- **My hours · BM (company without hour types) · the same honest
  sentence renders twice on one screen** — banner and card. Fix: drop
  one. (W2)

- **Agenda · CA (empty team week) · personal-variant empty copy on
  the TEAM week** — "when a manager assigns YOU a dated work block…"
  under a subtitle saying "The whole team's week". Fix: team-scope
  empty copy. (W2)

- **App boot screen · all roles · the first paint says "Loading…"**
  — untranslated English before a Dutch page. Fix: the same hardcoded
  NL/EN pair the shell brand line has, or a wordless spinner. (W3)

- **/my/employees · customers · informal "jouw" in a formal-u
  portal** — "Collega's binnen jouw organisatie…" while the page's
  own filter labels say u/uw. Fix: "…binnen uw organisatie…". (W3)

- **My hours · STAFF · subtitle "je", error banner "u"** — both
  registers on one screen. Fix: pick "u" (the portal standard). (W3)

- **Agenda · STAFF · "1 werk / 9 werken" in the day headers, "Te
  laat — 13 klussen" in the late bar** — two user-facing nouns for
  the same items on one screen (§D.2: one name per concept). Fix: one
  noun for a job on the whole board, both locales in lockstep. (W3)

- **/agenda role-guard · customers · the h1 says "Werkplanning" but
  the guard sentence says "Mijn werk is alleen beschikbaar…"** —
  "Mijn werk" is not this page's name anywhere else. Fix:
  "Werkplanning is alleen beschikbaar…". (W3)

- **Agenda stuck strip · STAFF · "Vastgelopen — actie nodig" over a
  body that says the manager acts** — the required worker sentence is
  present verbatim, but the strip header points the action at the
  reader. Fix: on the personal variant title the strip "Vastgelopen"
  without "— actie nodig". (W3)

- **/my/facturen at 390 · customer · the money page shows no
  amounts** — only NUMMER and GEBOUW visible; PERIODE, STATUS and
  TOTAAL sit inside the table's own scroll container (rule 7 holds,
  page overflow 0) with no visible scroll affordance. Fix: a
  card/stacked mobile variant (number + total first) or a visible
  scroll hint. (W3)

- **/my/facturen · customer (lotte) · PERIODE "—" on a SENT
  invoice** — a dash on a money row reads like an error where Tom's
  rows say "juni 2026". Fix: backfill/derive the period label, or say
  the send month. (W3)

- **/extra-work/new · customers · a 403 reaches the console on every
  open** — the documented custom-pricing degrade still logs "Failed
  to load resource: … 403"; rule 7 wants consoleErrors empty. Fix:
  precheck the permission (me flag) or swallow the expected 403. (W3)

- **My hours week-jump field · STAFF · the native date input renders
  "08/31/2026"** — the browser locale, not the app language, formats
  `<input type=date>`. Note only — browser-controlled; a custom
  picker would be needed to change it. (W3)

- **Tickets API · STAFF · a read of his own ticket's slot roster is
  refused with a write-shaped message** — `GET /tickets/328/
  staff-assignments/` → 403 "Staff cannot assign other staff to
  tickets." — he was not assigning anyone; the refusal describes an
  act that did not happen. The work-plan compensates as his read
  surface. Fix: a read-shaped refusal (or admit the read). (C1)

- **Ticket slots · crew-carry attribution names the customer as
  assigner** — slot 101 on ticket 328: `assigned_by = tom-customer-…`
  — Tom approved a quote; he never assigned staff. The carry (plan
  crew → ticket slot) stamps the transition's actor rather than the
  planner: a past-tense fact on the job that is not true (the P-13
  standard). Fix: stamp the planner. (C1)

- **Timesheets API · future-dated hours are accepted silently** —
  TimeEntry 54 (7.00h dated 2026-09-04) accepted on 2026-09-03 with
  no warning. Deliberate in the chain (hours on the planned day); the
  API not even flagging it is worth a look for the Hours surfaces.
  (C1)

- **Invoicing · a credit note exists briefly as a numbered-but-unsent
  invoice** (observation) — reversal creation returned invoice 40 as
  ISSUED with number 2026-0005 already assigned: "numbering at SEND,
  ISSUED shows CONCEPT" does not describe reversals. Consistent with
  a terminal mirror document, but the customer sees the original SENT
  invoice with no visible reversal until the credit note is
  separately sent (it does not auto-send). (C1)

- **Invoicing · preview and generate answer different questions about
  one month** (observation) — preview lists all unbilled EWs through
  the month (the ≤-period rule, Sprint 120's cure) while generate
  claims only the exact-period rows: 6 lines predicted, 1 produced.
  Both individually deliberate; the pair on one screen is the trap.
  (C1)

- **Recurring API · PATCH returns the WRITE echo (no `id`)** — create
  was fixed to return the read shape (P-12 E2 / §D.24 rule 4) but
  update was not. (C2)

- **Extra work API · a provider CANCELLED transition accepts an empty
  note, and an unknown `reason` key is silently dropped** — the
  serializer field is `note`; cancel-with-reason is enforced only by
  the frontend dialog (only CUSTOMER_REJECTED has a mandatory
  reason). (C2)

## Questions for the owner — ANSWERED (P-15 Part 0, 2026-09-03; the
## owner holds a one-word veto on each — Addendum D §D.24.7)

- **A building manager is a full invoice operator.** → **RULED (0.1,
  H-12): committing is company-level.** Issue/send/un-issue/reverse
  are CA/SA only; BM keeps drafts, preview, edits, lists; the refusal
  names the next actor (`invoice_admin_only`). Veto word: "BM may
  send".
- **Should only APPROVED agreed-hours patterns fill the sheet?** →
  **RULED (0.2): yes.** One query filter + the pin
  (`test_p15_approved_fill`) + the grid's why-empty line.
- **Who signs off completion on AUTO_START work at a view_own-only
  building?** → **RULED (0.3): the manager's check counts as the
  sign-off, and the screen says so** ("Checked by {manager} — counts
  as approved (this customer cannot approve online)"). Never a
  provider override in silence.
- **Is a customer's wish date allowed to place a spawned ticket on
  the board?** → **RULED (0.4): never.** One placement law, no
  exceptions; the wish is a strip FACT (`wished_day`). Veto words:
  "keep the wish on the board".

## Pre-existing reds ("don't trust the tests we have" — confirmed)

- **Four tests were already red on the P-13 tip `47d9998`** (verified
  by re-running them with P-14's backend change stashed):
  `test_p1_honest_dates.ReviewCarryTests` (all three) and
  `test_w_fix1_work_plan::test_both_kinds_answer_the_same_key_set`.
  The ReviewCarry trio were STALE PINS of pre-P-10 review placement
  (P-10 A2 made review placement personal; the tests still asserted
  the old today-card for a company admin and a past-week column for
  the worker) — red from P-10 to P-14 because the p1 module was never
  in a later sprint's touched set. **FIXED (P-14)**: rewritten to the
  P-10 semantics `test_p10_review_placement` pins. The lesson stands
  for the report: a green gate on "the touched modules" can sit on
  top of neighbouring reds for four sprints.

## B6 — the state-machine sweep's verdict (2026-09-03)

354 HTTP attempts against the four guarded machines (ticket 191
illegal + 5 legal, extra work 85+4, proposal 31+3, invoice 30+5), as
SA and CA, in-process against the dev stack inside one rolled-back
transaction (rollback proven by before/after marker counts and a
zero-hit fingerprint sweep): **zero illegal transitions allowed, zero
non-sentence refusals, zero 500s.** The legal legs proved the probe
drove the real doors (auto-close rode the customer's approval to
CLOSED; send allocated `2026-0004` transactionally and the rollback
left no gap; reverse 201; draft delete 204). Skipped and recorded:
the contract machine (the S1 above — there is nothing to probe),
week-lock double-close, recurring archive idempotence,
planned-occurrence guards, bulk-status, direct-publish.

## Observations (no user-visible defect today; recorded for web-Claude's comparison)

- A COMPLETED extra work with **no completion history row and no
  provider plan** is now on no board at all (before A5 it hung on the
  customer's wish). Real completions write history in-transaction, so
  only pre-history-era data could hit this; the EW list still shows
  the row. Same for CUSTOMER_REJECTED / CANCELLED wish-only rows —
  the list's Cancelled view (P-8 guard) remains their home, and EW
  `SETTLED_DAY` has no blocked leg to hang them by (a pre-existing
  gap, now visible).
- **The two-customer switch is untestable on this seed.** Amanda has
  exactly ONE membership (B Amsterdam, building B3) and her Settings
  truthfully says "1 bedrijf · 1 gebouw · 1 klant"; no switcher
  exists and none is missing. Per the inventory the ONLY
  multi-customer affordance is the /my/documents picker, while
  StartPage, MyMeldingen and MyEmployees hardcode `customer_ids[0]` —
  seed a second membership and those three pages showing only the
  first customer would be a real S2. (W3, C2)
- **Closed-by-default guide folds cost nothing.** Where a fold exists
  the page ALSO carries its key consequence sentences outside it —
  the cold read never depended on opening one. But the missing
  sentences (the Edit/bulk toolbar, the catalogs multiplier, the
  tickets month-scope) are not IN the folds either: not one W1
  finding would have been prevented by defaulting folds open. The
  cheap fix is one bulk-toolbar line per fold plus a labeled toggle.
  (W1)
- **Zero cross-tenant leakage anywhere.** Every Bright walk grepped
  for "Amsterdam"/"Osius": zero hits; Lotte saw only R1/R2 Rotterdam
  data; server-side probes (`/api/customers/`, `/api/buildings/`,
  `/api/companies/`) returned only own-tenant rows for every walked
  role. (W1, W2, W3)
- **The chains' positive verifications hold**: the money ledger
  reconciled to €0.00 at every seam (quote → actual → final → invoice
  → credit note); `plan_requirements_unmet` names all four missing
  pieces; `actual_hours_required` and `final_amount_locked` speak
  human sentences with stable codes; the reversal release predicate
  held end-to-end; the on-behalf approval wrote its
  `is_override:true` history row; ISSUED invoices stay invisible to
  the customer until SENT. (C1)
- Behaviors confirmed as documented (C2): plain view_own customers
  never see provider-spawned recurring visit tickets (the RBAC
  default); `extra_work_billing` is a detail-only field; contract
  create rejects `IN_ADVANCE` (valid: ADVANCE/ARREARS); week
  close/reopen, fill idempotency and the invoice-lock ordering on
  actual-hours all behaved exactly as written.

## The numbers

- 76 surfaces / ~930 capabilities inventoried
  ([capability-inventory.md](capability-inventory.md)).
- 344 page-walk records across 18 role-width walks (9 roles,
  1440 + 390 passes); overflowPx = 0 on every record.
- 7/7 chains completed, 64 recorded steps; every mutation listed and
  fixtures left labeled for the owner.
- 354 state-machine attempts — 0 illegal transitions allowed.
- 194 GET endpoints × 9 roles probed — 0 500s, 0 tenant leaks.
- E2e (Playwright, full suite, once): **377 passed · 19 failed ·
  6 skipped** (1.2h, run while the backend suite loaded the box).
  Every failure classified (`e2e-classification` in the sprint
  bundle): **0 P-14 regressions**; 11 stale pins — 15 of the 19 are
  FE-7's own standing open-red population (the checklist's ledger),
  and three broke later without anyone noticing (the
  `ticket-extra-work-origin` testid trio at P-13, a fact-block pin
  at P-4, the catch-all page pin at P-5); 6 are one deterministic
  e2e-fixture defect (`pageApiGet` hardcodes `localhost:8000`, which
  the dev backend's ALLOWED_HOSTS refuses — FE-7 fixed the sibling
  helper and missed this one); 1 dev-container collectstatic gap
  (/django-admin 500 in the harness only); 1 true load flake. The
  cross-company pair failed MECHANICALLY with zero cross-tenant rows
  ever in the DOM — the same run's real isolation tests all passed.
  P-15 line: fix `pageApiGet`, re-pin the three late-broken specs,
  then re-run — the suite's standing reds have hidden real signal
  since FE-7 ("don't trust the tests we have", proven twice today).
- Full backend suite, once, on Postgres (information, not the
  verdict — the brief's own words): **Ran 6007 tests in 24078.838s —
  FAILED (failures=43, errors=8, skipped=3)**. The 51 reds sit in
  modules P-14 never touched (sprint-28-era audit pins, sprint-109/
  123/127/142 extra-work modules, seed-demo isolation pins, the
  sprint-179 week-grid-source quartet, b7/w3g/sprint7b) — the suite
  has not run in full since the 2026-08-06 testing-gate ruling, and
  the reds accumulated unseen. The ONE board-adjacent red
  (`test_p4_waiting_drawer::test_approving_on_the_customers_behalf…`)
  was re-run against the BASE `views_work_plan.py` from `47d9998`
  and fails identically there — pre-existing (its fixture writes no
  send/review stamps, so the settle falls to today's approval
  moment), not a P-14 regression. Every module P-14 touched is green
  in its final state. P-15 line: triage the 51 (most look like the
  same stale-pin class the sweep found four more of) — a monthly
  full-suite run would have caught them the sprint they broke.
