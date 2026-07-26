# Osius — Source of Truth · Addendum B (Invoicing)

**Date:** 2026-07-26. **Status:** authoritative; extends `source-of-truth.md`.
Section references point at the base SoT. Where this addendum and the base SoT
differ, **this addendum wins** for the items it covers.

The base SoT (2026-05-30) and Addendum A (2026-06-05) predate the invoicing
subsystem, which shipped across PR #110–#114. The subsystem's lifecycle is
described nowhere else that is current (the sprint checklist's LOCKED DECISIONS
block was wrong — it said numbering is assigned at ISSUE; the code assigns it
at SEND). This addendum is the authoritative description. Every claim below was
verified against `backend/invoicing/` on branch `feat/sprint-115`.

---

## B.0 What the subsystem is
A provider **Invoice** bills one customer (optionally scoped to one building)
for that customer's unbilled **Extra Work**, plus an optional free-text fee
line. There is no contract entity and no recurring contract-fee: an invoice is
a roll-up of earned Extra Work. Models: `invoicing/models.py`
(`Invoice`, `InvoiceLine`, `InvoiceNumberSequence`).

## B.1 Lifecycle
`DRAFT → ISSUED → SENT`, forward-only, with two extra moves
(`invoicing/state_machine.py`):
- **Un-issue** `ISSUED → DRAFT` ("terug naar concept", `unissue_invoice`).
- **Reversal** of a SENT invoice (`reverse_invoice`) — an auto-generated
  negative credit note. **Reversal is TERMINAL: a reversal cannot itself be
  reversed** (`reverse_invoice` rejects `is_reversal`).

A DRAFT is created by generation (`services.generate_draft_invoices`) and is
freely editable (page-1 summary + fee via `update_invoice_meta`; lines via
`add`/`update`/`remove` in `line_services.py`). Generation is idempotent —
it claims the Extra Work it rolls up, so a second run finds nothing unbilled
and creates no empty draft.

## B.2 Numbering — assigned at SEND, not at issue
Numbers are gapless `"YYYY-NNNN"` (zero-padded to 4 digits, widening past
9999), **per-company per-year**, allocated from a row-locked
`InvoiceNumberSequence` (`numbering.allocate_invoice_number`,
`select_for_update` on the one sequence row — the tickets state-machine
locking pattern).

The number is assigned **at SEND, not at issue**
(`state_machine.send_invoice`). Consequences, all deliberate:
- An **ISSUED-but-unsent** invoice has no number yet and therefore displays
  **CONCEPT**.
- `send_invoice` allocates **only when `number is None`**, so a **reversal**
  (born `ISSUED` with its own number, allocated at creation) is never
  re-numbered, and any legacy numbered-ISSUED row keeps its number.
- The numbering **year** is the Amsterdam-local calendar year at allocation
  time (send time for a normal invoice, creation time for a reversal), **not**
  the invoice's billing `period_year`.
- The PDF number slot renders `invoice.number or "CONCEPT"`
  (`invoice_pdf.py`) — it never prints `"None"`.

## B.3 Un-issue is not delete
`unissue_invoice` (`ISSUED → DRAFT`) guards: provider-operator; status is
`ISSUED`; the invoice is **not** a reversal; and it is **not** already
numbered (a numbered row is forward-only — dropping its number would leave a
gap, so it can only be sent). It flips **only** `status` and `issued_at` and
**does not release the Extra Work claims** — the draft's `InvoiceLine`s keep
them and `is_invoiced` stays set. **Un-issue is not a delete**: the work stays
claimed, ready to re-issue. (Releasing claimed work is `delete_draft_invoice`,
a separate DRAFT-only soft-delete.)

## B.4 Immutability & reversal
A **SENT invoice is immutable** (`assert_mutable`; the only non-DRAFT mutation
path is reversal). A correction goes through `reverse_invoice`, which:
- creates an auto-generated **negated mirror** invoice (born `ISSUED`, carrying
  its own number, `is_reversal=True`, `reverses=original`, negated totals and
  negated mirror lines with `extra_work=NULL` — it is a monetary counter-entry
  and does **not** re-claim work); and
- releases the **original's** Extra Work back to the unbilled pool
  (`is_invoiced=False`, `invoiced_at=NULL`). The original stays SENT on the
  books — it is **not** soft-deleted.

**Non-obvious correctness detail (preserve this):** reversal sets the original
Extra Work's `is_invoiced=False`, but the original's `InvoiceLine` **still
points at that Extra Work**. The work returns to the unbilled pool only because
the live-claim subquery in `selectors.unbilled_extra_work` scopes on
`invoice__reversed_by__isnull=True` — a reversed original's claim stops
counting. Anyone editing that selector must keep this predicate, or reversed
work silently disappears from billing.

## B.5 Billing schedule (informational)
On `customers.Customer`:
- `invoice_day_rule` — `FIRST_OF_MONTH` / `LAST_OF_MONTH` (blank = unset).
- `invoice_day_of_month` — nullable `1–28`, and **takes precedence** over the
  rule when set (capped at 28 so the day exists in every month; use
  `LAST_OF_MONTH` for month-end).

Effective billing day = the specific day if set, else the first/last rule, else
unset. The schedule is **purely informational**: it only surfaces a customer in
the `/due/` "who's due" list (`views.InvoiceViewSet.due`, `is_due` hint). It
does **not** auto-generate invoices and does **not** auto-send. Generation and
send are always explicit operator actions.

## B.6 Granularity
`Customer.invoice_granularity_default` defaults to **CUSTOMER** (one invoice
covering all of the customer's buildings) and is overridable at generation
time (`PER_BUILDING` = one draft per building with unbilled work). Every Extra
Work row is tied to exactly one building, so a customer-level invoice is simply
all its buildings' Extra Work combined (`services.generate_draft_invoices`).

## B.7 The three Extra Work money values
- **`total_amount`** — the quoted/proposal estimate. It is €0 for unpriced
  work (ad-hoc / needs-provider-pricing lines that never resolved to a price).
- **`final_total_amount`** — the actual-hours final amount, computed by
  `extra_work.final_amounts.recompute_final_amounts`. NULL until frozen.
- **earned** — `rowAmounts()` in `frontend/src/lib/billing.ts`:
  **final-with-quoted-fallback** (use `final_total_amount` when present, else
  fall back to `total_amount`). The backend mirror is
  `invoicing.services._earned_amounts`.

**Binding rule: `earned` is the ONE billing-total rule; every money surface
(dashboard widget, Facturen page, generated invoice line) must use it.**

Two supporting facts:
- **Actual hours apply only to HOURLY Extra Work.** For every other unit type
  (fixed / item / m² / other) the final amount bills the ordered quantity
  (`final_amounts.billable_quantity`; the actual-hours endpoint rejects a
  non-hourly line with `actual_hours_not_hourly`).
- **The final amount locks once a spawned operational ticket is APPROVED or
  CLOSED.** It is frozen (recomputed + persisted) at ticket APPROVED
  (`tickets.state_machine`), and further actual-hours edits are then refused
  with `final_amount_locked` while the ticket is APPROVED/CLOSED
  (`extra_work/views.py`). **REJECTED does not lock.**

## B.8 Scoping & visibility (defence in depth)
Two separate scopes (`invoicing/selectors.py`):
- **Provider** — `scope_invoices_for`: SUPER_ADMIN sees all; COMPANY_ADMIN
  sees their companies'; BUILDING_MANAGER sees the companies they manage a
  building in; everyone else none. Company-granularity, so both customer-level
  (building NULL) and per-building invoices are covered.
- **Customer** — `scope_customer_invoices_for`: a `CUSTOMER_USER` sees only
  **SENT** invoices of the customer(s) they are a member of. Separate from the
  provider scope; it never widens provider visibility.

Every `InvoiceViewSet` action is gated by `_forbid_non_operator` (a non-
operator gets a stable 403, never an empty 200/404); the issue/send/unissue/
reverse actions inherit it via the `_transition` helper, **and** each
state-machine function **independently re-checks** `_is_provider_operator`.
That double gate is deliberate defence in depth — keep both. The PDF endpoint
(`InvoicePdfView`) and the customer read surface (`/api/invoices/my/`) are
gated the same way through their respective scopes.

## B.9 PDF branding
`backend/config/pdf_branding.py`: `is_platform_brand(company)` matches
`company.slug` against `settings.PLATFORM_BRAND_SLUG`. A match renders the
OSIUS designed branding; otherwise the invoice/report renders neutral
(name-only header). A cross-company report renders with `company=None`, which
is neutral by construction.

**Deployment trap:** `PLATFORM_BRAND_SLUG` defaults to `"osius"`
(`config/settings.py`), and the crmtest environment sets `"osius-demo"`. **In
production it must be set to that environment's real OSIUS company slug — if it
does not match, OSIUS's own invoices render unbranded.**
(`backend/assets/branding/osius_logo.png` is the committed platform logo asset.)

## B.10 FIXED (Sprint 119) — the `/due/` panel now reports through the current month
Previously a KNOWN GAP: the `/due/` endpoint (`views.InvoiceViewSet.due`)
hard-anchored to the current Amsterdam-local month only
(`year, month = today.year, today.month`), so unbilled work from a **prior**
month silently dropped off the panel once the month rolled over, and a
`LAST_OF_MONTH` customer was flagged `is_due` on exactly one calendar day.

**Fix landed:** `due` now calls a new selector,
`selectors.unbilled_extra_work_through(actor, company_id, customer_id, year,
month)`, which matches every earned-but-unbilled row billable in `(year,
month)` **or any earlier period** (tuple comparison), instead of the exact
`== (year, month)` match. `generate` (`services.py`) is untouched — it keeps
calling the original exact-period `unbilled_extra_work`, since invoice
generation still always targets one specific period. `is_due` keeps its
existing schedule-hint semantics (billing day reached AND unbilled_count >
0); the response shape is unchanged (`period_year`/`period_month` still
report the current cutoff period). Covered by
`InvoiceDueApiTests.test_due_includes_unbilled_work_from_a_prior_month` in
`backend/invoicing/tests/test_api.py`.
