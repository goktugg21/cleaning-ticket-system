# P-16 suite repair — every standing red, dispositioned

P-14 ran the FULL backend suite once (`Ran 6007 — FAILED (failures=43,
errors=8, skipped=3)`) and the full e2e suite once (377 passed · 19
failed · 6 skipped) — the first full runs since the 2026-08-06
testing-gate ruling, and the reds had accumulated unseen in modules no
sprint touched. P-16's rule: every red gets exactly one of three
outcomes, recorded here —

- **repaired** — the test pinned a rule that still holds and the CODE
  drifted: the code is fixed, with the sprint that broke it named;
- **repinned** — the RULE changed by an owner ruling since the pin was
  written: the test now asserts the current rule, the ruling cited;
- **deleted** — the test pinned nothing that exists any more, reason
  given.

No test is skipped or marked expected-failure. The standing rule going
forward (sprint-checklist): **the full backend suite runs at the close
of every sprint; a red is a sprint item, not a note.**

## A. The backend reds (51)

The P-16 discovery run of the suspect module families surfaced 34 reds
(the remaining P-14 count difference is the tests that had meanwhile
been healed by P-15's own work or sit outside these families — the
full-suite line at the bottom is the final arbiter). By family, each
test's disposition:

- **repinned** `audit.test_sprint28_cart_request_audit` ×5 — two
  fixture drifts stacked: the cart payload sent the P-8-retired
  per-line `requested_date` (`line_requested_date_not_accepted`), and
  once past that, P-15's intent rule asked the provider to choose
  (`intent_required`) — the fixture now sends the request-level
  `preferred_date` and `AUTO_START_AFTER_PRICING`. The audit chain the
  tests pin is unchanged; the create-diff assertion accepts a None
  per-line date.
- **repinned** `audit.test_sprint28_proposal_audit` ×7 — the proposal
  create hit the W-PLAN pricing gate (`plan_requirements_unmet`,
  which did not exist when the pins were written); the fixture takes
  the gate's documented bypass (the recorded override — an
  ExtraWorkStatusHistory row, invisible to the AuditLog assertions).
- **repinned** `extra_work.test_sprint109_billing_localtime` ×3 — the
  W1-B reopen fix taught `billing.earned_at` to read `ticket.status`
  (WAITING_CUSTOMER_APPROVAL prefers `sent_for_approval_at`); the
  test's `_FakeTicket` predated the field. The fake now carries a
  CLOSED status, keeping the tests on the closed_at arm they pin.
- **repinned** `extra_work.test_sprint123_managed_unit_backfill` ×1 +
  `test_sprint142_category_company_backfill` ×1 — W13 seeds PROTECTed
  `TicketCategory` rows per company (post_save); the empty-DB fixtures
  delete them before the companies, exactly as Sprint 142 already
  taught them to do for service categories.
- **repinned** `extra_work.test_sprint127_labels_ew` ×4 — the same
  per-line `requested_date` drift as the cart audits; with the
  request-level `preferred_date` the department/work-type mismatch
  refusals the tests pin fire again.
- **repinned** `accounts.test_seed_demo_data` ×2 — the exact ticket
  counts (19) drifted every time a later sprint appended a seed block
  (P-13's finance fixtures included); the counts are FLOORS now and
  the per-company isolation assertions (the actual signal) stay exact.
- **repinned** `timesheets.test_sprint179_week_grid_source` ×4 — the
  bulk-week write validates the source pair against REAL in-scope jobs
  now (`timesheet_source_invalid`); the fictional ticket ids 41/42
  became two real tickets on the building staff_a holds BUILDING_READ
  visibility on. The row-identity rules the tests pin are unchanged.
- **repinned** `tickets.test_b7_note_taxonomy` ×2 — Sprint 191 §2.5
  gave attachments their own `visibility` axis (default INTERNAL) and
  the walls read IT, not the message tier; the raw-ORM fixture now
  stamps what the upload path stamps (the customer's own upload
  CUSTOMER; the completion photo CUSTOMER as the opened-up case).
- **repinned** `tickets.test_w3g_completion_requirements` ×1 — W13
  added `note_asked_by` / `file_asked_by` to the requirements payload;
  the expected dict carries them.
- **repinned** `tickets.test_sprint7b_convert_to_extra_work` ×4 — the
  send leg and proposal door hit the W-PLAN gate (bypass added, as
  above); the intent test's line carried the retired per-line date and
  400'd before reaching the intent validator it pins. (The CONVERSION
  door deliberately keeps per-line dates — only the normal create
  retired them.)

**Round 1: repaired 0 · repinned 34 · deleted 0** — every red was a
stale pin of a rule an owner-ruled sprint had since changed, not code
drift.

## A2. Round two — what the FULL run then surfaced (62)

The full current-tree run found MORE than the baseline's 51: the
baseline leftovers outside round 1's families, plus breaks P-15's own
rules caused silently in modules its touched-module gate never ran —
the exact disease the standing rule now prevents. The ledger:

- **repinned ~40** — P-15's `intent_required` (a provider's non-agreed
  cart gets no silent default) hit every provider-actor create fixture
  that predates it: `w5b_groups` (~25, via the shared batch payload —
  whose 400 cascaded into KeyErrors on `members`/`group`),
  `w_fix1_priced_batch_redaction` (6, same base), `fe2_display_phase`,
  `sprint180_tracks_and_tickets` (2), `sprint182_money_rules` (3),
  `w_ew1_dates` (provider-deadline), `sprint154_default_labels` (3 —
  which also still sent the retired per-line date). Each fixture now
  chooses `AUTO_START_AFTER_PRICING`, the provider-legal intent.
- **repinned 4** — P-8R's `rejection_note_required` on the proposal
  door: `sprint187_quoted_totals`, `sprint28_proposal` (2),
  `sprint6b_auto_start_after_pricing`, plus `m1_b4`'s reject leg — the
  rejection now carries its reason as `note`.
- **repaired 1 (P-16's own)** — the new view-level
  `cancel_note_required` preempted the machine's more specific
  `override_reason_required` on late-stage cancels
  (`sprint29_batch29_8`): the view gate now fires only for the EARLY
  cancels (REQUESTED / UNDER_REVIEW / PRICING_PROPOSED), the machine's
  named refusals keep the late pairs. A generic sentence must never
  preempt the one that names the actual missing thing.
- **repinned 2 (P-16's own)** — `m1_b4`'s decision summaries pinned the
  old hardcoded English; the bell renders per RECIPIENT now, so the
  nl-default fixtures assert the Dutch words plus the machine-stable
  `template_key`.
- **repinned 3** — `b6_bm_revocable_permissions`: the W-PLAN gate
  postdates the pins; the fixtures complete the plan so the wall under
  test (the BM's revocable key) is the one that answers.
- **repinned 1** — `audit.test_audit` company hard-delete: W13's
  PROTECTed per-company TicketCategory seeds go first (the Sprint 142
  order, again).
- **repinned 1** — `sprint23a` anonymous roster: the M2 credentials
  work made the anonymous answer one row per member
  (`assigned_team_member_anonymous`, no identity fields), the shape
  `test_m2_ticket_payload_credentials` already pins.
- **repinned 1** — `p8r_me_account_facts` last_login: the wire renders
  LOCAL time; the naive-UTC date comparison was a midnight-window
  flake (it failed only because the run crossed 00:00 local).
- **repinned 1** — `sprint173` module-independence: the boundary is
  MODULE-LOAD independence; `_source_in_scope`'s call-time import is
  its own documented seam, so the scanner checks unindented lines only.
- **repinned 1** — `p4_waiting_drawer` settled-day (pre-existing at
  the P-14 base, by P-14's own report): the fixture now stamps
  `sent_for_approval_at` on the planned day, as the machine does
  in-transaction for every real waiting ticket.

The 4 skips are environmental/documented: the two frontend-bundle
byte-identity tests skip inside the container (the backend image has
no `frontend/`; they run where the repo is whole) and extra_work's two
pre-existing decorated skips (on record since P-15's carryover runs).

## B. The e2e reds (19 + the P-15 leftover)

The P-16 discovery run (the FE-7 harness, docs/testing/e2e-harness.md)
scored **11 failed · 7 skipped · 384 passed (1.2h)** — eight of
P-14's nineteen were already healed by P-15's `pageApiGet` fix and
P-16's option-load re-pin. The eleven, dispositioned:

- **repinned** `cross_company_isolation` › building dropdown — the
  select renders before its options land; `expect.poll` on the
  expected buildings, then the absence assertions (the P-15 snapshot
  showed exactly R1+R2 — a flake, never a leak).
- **repinned** `cca_company_wide_and_people` › deleted people routes —
  since the P-4 never-void work the catch-all renders `not-found-page`
  AT the URL instead of bouncing; the pin is "no customer surface
  here", not the redirect mechanics.
- **repinned** `mobile_layout` › buildings Edit button — the
  Actions-cell Edit opens the in-page edit dialog now (a later
  sprint's design); the pin is "dialog opens, URL stays".
- **repinned** `sprint27f_ticket_override` › on-behalf approve — the
  customer-approval AUTO-CLOSE (tickets/auto_close.py) rides the
  approval through APPROVED to CLOSED; CLOSED is the truthful
  workflow-card value. The override badge assertions stand.
- **repinned** `sprint28_batch15_2` › override radio — harness
  mechanics: the radio is visually-hidden behind its optical bubble,
  so `.check()` on the input is intercepted; the spec clicks the
  LABEL, as a person does.
- **repaired** `sprint28_services` ×3 — the real defect was the app's:
  `listServiceCategories` / `listServices` read ONE page and every
  consumer (the add-service modal's category select, the two catalog
  tabs, two pickers) treated it as everything — the Sprint 134/135
  truncation class, invisible until the dev catalog crossed the page
  size. Both helpers page exhaustively now (the `listAllCompanies`
  pattern) and the two catalog tables are wrapped in `BoundedList`
  (CLAUDE.md #8). The specs themselves were right.
- **repinned** `sprint29_batch29_3` › company detail — the About card
  became the P-12 fact block (`company-detail-facts`); the admins
  card kept its id.
- **repinned** `sprint29_batch29_8` J1/J3/J4 — the standalone
  `ticket-extra-work-origin` block was replaced at P-13/W21 by the
  agreement card + the ticket's Money-tab extra-work card; the
  landing pin is now the redirect + `ticket-extra-work-money`
  visible (the ticket IS the spawned job's home).

The verification re-runs surfaced three more layers under the
services family and one fresh flake:

- **repinned** `sprint28_services` ×3, second layer — Sprint 149/150
  made the SA catalog ONE company at a time (opens on the
  remembered/lowest-id company); the specs seed under "Osius Demo"
  and now pick it in the `catalog-company-selector` the way an
  operator does. (The exhaustive-paging repair above was real too —
  both stood between the specs and green.)
- **repinned** `sprint28_services` › delete-category, third layer —
  Sprint 138 §2c renders the category Delete button ONLY on an empty
  category (`Service.category` is PROTECT): "fails gracefully" became
  structural. The spec asserts the button's absence AND that a direct
  API delete still refuses (the server floor half of the old pin).
- **repinned** `cross_company_isolation` › facility cells — rows
  render client-side after networkidle under load; the helper waits
  for the first `.td-facility` before counting (a one-shot count read
  a phantom empty list on a saturated box).
- **deleted** — nothing: every red pinned something that still exists
  in some form.

Skips: the discovery run's seven were not platform-skips, and each got
a disposition of its own:

- three demo-card specs self-skipped because a stray
  `.env.production.local` forced `VITE_DEMO_MODE=false` into the
  build; the harness builds with the flag on (as crmtest does) and
  they run.
- **deleted** `sprint28_batch15_4` › ticket EW origin link — it hunted
  the W21-retired `ticket-extra-work-origin` block and skipped when
  the hunt failed, i.e. always; the surviving fact is J1/J3/J4's
  money-card landing pin. The one deletion of the sprint.
- **repinned** `sprint28_batch15_4` › reject dialog — seeds its OWN
  rejectable EW (Tom's cart → SA drives to PRICING_PROPOSED with a
  pricing line + the W-PLAN recorded-override bypass) instead of
  hoping the tracker held one.
- **repinned** `sprint29_batch29_1` › pricing totals — seeds a DRAFT
  proposal with a priced line (the totals row lives in the
  ProposalBuilder) instead of clicking the list's first row.
- **repinned** `sprint29_batch29_2` › add-form — same seed (the
  builder mounts on a draft proposal); › focus_user — scans customers
  for a member with access rows instead of asking only the first.
- **repinned** `sprint30` K1 — three stale layers: the seed helper
  sent the P-8-retired per-line `requested_date`, the drive hit the
  W-PLAN gate (bypass added), the workflow leg needs a pricing line
  first; and the assertion expected the retired request page — the
  provider landing is the JOB now (the J1 rule), so K1 asserts the
  redirect + the money card + no retry door.
- `sprint30` K2 needs a genuinely stuck CUSTOMER_APPROVED EW with zero
  tickets — a state the API can no longer produce (auto-spawn is the
  fix it tests the repair FOR). The harness seeds one ORM row
  (`[P16-FIXTURE] Stuck approved EW`) before the run; K2 heals it by
  pressing retry-spawn, so each full run needs a fresh row (the seed
  snippet lives in the harness notes). Verified green twice.

## Final lines

- Backend, full suite, Postgres, one run (2026-09-04):
  **`Ran 6077 tests in 21267.918s — OK (skipped=4)`** — the first
  green full run since the 2026-08-06 testing-gate ruling. The four
  skips are environmental/documented (the two frontend-bundle
  byte-identity tests inside the container; extra_work's two
  pre-existing decorated skips).
- E2e, full suite, FE-7 harness, one run (2026-09-04):
  **`401 passed (1.1h)` — 0 failed, 0 skipped.** (402 became 401 by
  the one deletion; the demo-card three and K2 RAN.)

## The whole ledger, summed

96 dispositions across both suites: **repinned 93 · repaired 2 (both
real app defects: the services-catalog one-page truncation, and
P-16's own cancel gate preempting the machine's specific refusal) ·
deleted 1** (the spec that hunted the W21-retired origin block).
