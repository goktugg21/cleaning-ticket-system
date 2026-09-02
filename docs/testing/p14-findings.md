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

---

## S1

- **Contracts · SA/CA · the contract's lifecycle has no state machine
  at all** — `Contract.lifecycle` is a plain writable ChoiceField on
  the detail serializer (`read_only_fields` covers only
  id/contract_no/timestamps), so `PATCH /api/contracts/<id>/
  {"lifecycle": "..."}` performs ANY jump with a 200: a CANCELLED
  contract back to ACTIVE, an ACTIVE one silently to DRAFT (which
  stops its invoicing), no confirm, no history surface, no refusal
  except DRF's `invalid_choice` (EXPIRED is unstorable by
  CheckConstraint). Every other money-adjacent machine (ticket, extra
  work, proposal, invoice) has an explicit ALLOWED_TRANSITIONS guard;
  this one has none. Found by the B6 state-machine sweep. NOT fixed
  in-sprint — the legal-transition set is a design decision inside
  the frozen contracts model (the owner's meeting decides the model;
  a guard + history + a dedicated activate/cancel surface is a P-15
  sprint item, top of the list). The UI's own buttons drive sensible
  values, so the exposure is API-level and operator-role-gated, not
  public.

## S2

- **Hours › Agreed hours · SA/CA · the approval road gates nothing in
  the fill** — `timesheets/fill.py::_agreements_for_week` seeds the
  week grid from `auto_fill=True` alone, with NO status filter: a
  DRAFT pattern with "Fills the sheet" on fills people's weekly
  sheets exactly like an Agreed one, so Draft → Submitted → Agreed is
  decoration for the fill. Found while verifying the A1 rule-8 fold
  (which now tells the truth of the code). Fix: a ruling first —
  "only APPROVED patterns fill the sheet" is one query filter + a pin
  if the owner wants it; the fold and the road teach then change one
  word. (Evidence: `backend/timesheets/fill.py` lines ~120-127; no
  status anywhere in the fill module.)

- **Contracts › Types tab · BUILDING_MANAGER · write controls that
  always refuse** — `ContractTypesTab` renders its add/edit/delete
  controls unconditionally, but the backend gates every contract-type
  write behind `IsContractManager` (BM is READ-ONLY on the whole
  contracts module, `backend/contracts/permissions.py`). A BM opening
  Contracts › Types (ContractsRoute admits BM as a reader) sees
  controls that 403 on press — the "control that lies" defect class.
  Fix: mount the tab with the page's existing `canManageContracts`
  answer and hide the write controls. **FIXED (P-14)** — see Part B
  fixes.

## S3

- **My schedule / Recurring work board · manager/SA · a spawned
  ticket is still placed by the customer's wish** — P-14 A5 removed
  the wish fallback for EXTRA-WORK rows (a wish is not a plan), but a
  ticket spawned from an extra work with only a `preferred_date` is
  still placed in that day's column through `tickets/job_dates.py`
  (pinned by `test_fe4_honest_dates::
  test_a_customers_wish_is_a_wish_not_a_plan` and `test_p1_honest_
  dates::test_the_wish_behind_a_phantom_is_still_a_wish` — placed,
  captioned `CUSTOMER_WISH`, `has_real_plan=false`). The caption is
  honest, but the same owner ruling ("a wish date is not a plan")
  read strictly puts these in the Not-planned strip too. Needs a
  ruling before touching it: W-PLANTRUTH's "one fact places the
  board" and P-1's captioned-phantom design pull in opposite
  directions here.

## S4

- **Invoices · API · refusal shape drift** — an illegal invoice
  transition returns a 400 with a human sentence but NO stable
  `code`, unlike every other machine's `{"detail", "code"}` shape
  (`invoicing/state_machine.py`); and the ticket status endpoint
  wraps `detail`/`code` in one-element lists. Human sentences do
  reach the screen through `getApiError` (P-8 A3 holds), so this is
  an API-consistency item, not a user-facing one. P-15: give the
  invoice refusals codes; unwrap the ticket endpoint's lists.
- **Recurring work · API · archive/unarchive are idempotent with no
  refusal** — re-archiving an archived rule answers 200. Harmless
  (the act is idempotent), recorded for the machine table's
  completeness.

- **Hours (worked) · SA/CA · the empty week's sentence named a button
  that does not exist** — NL `week_empty_body` said "Druk op *Uren
  invullen*" while the button says "Uren invoeren". **FIXED (P-14)**
  in the A1/A4 i18n pass (both locales now name the button and the
  agreed-hours source).

## Questions for the owner (documented design, worth a confirmation)

- **A building manager is a full invoice operator.** `PROVIDER_ROLES`
  (SA/CA/BM) gates every `InvoiceViewSet` write — a BM can generate,
  issue, SEND (allocates the gapless number) and reverse invoices for
  any company they manage a building in. This is documented design
  (Addendum B §B.8's operator gate), not a defect — but sending
  invoices is a company-level money act, and the owner may want it
  CA-only. One sentence from the owner settles it.

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

## Observations (no user-visible defect today; recorded for web-Claude's comparison)

- A COMPLETED extra work with **no completion history row and no
  provider plan** is now on no board at all (before A5 it hung on the
  customer's wish). Real completions write history in-transaction, so
  only pre-history-era data could hit this; the EW list still shows
  the row. Same for CUSTOMER_REJECTED / CANCELLED wish-only rows —
  the list's Cancelled view (P-8 guard) remains their home, and EW
  `SETTLED_DAY` has no blocked leg to hang them by (a pre-existing
  gap, now visible).
