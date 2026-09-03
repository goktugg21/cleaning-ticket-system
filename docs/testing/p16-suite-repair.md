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

<!-- Filled from the P-16 full-suite run; one line per test. -->

(pending — the P-16 full-suite run is in flight; each red lands here
with its disposition as it is triaged)

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

- Backend, full suite, Postgres, one run: (pending)
- E2e, full suite, FE-7 harness, one run: (pending)
