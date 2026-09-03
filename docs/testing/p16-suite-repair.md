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
- **deleted** — nothing: every red pinned something that still exists
  in some form.

Skips: three were build-config (the demo-card specs self-skip when
the build has `VITE_DEMO_MODE=false`; the final run builds with it on,
as crmtest does), the rest are data-conditional and enumerated with
the final run's list reporter.

## Final lines

- Backend, full suite, Postgres, one run: (pending)
- E2e, full suite, FE-7 harness, one run: (pending)
