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
operator gets a stable 403, never an empty 200/404). **P-15 §0.1 / H-12
tightened the four COMMIT actions**: issue/send/unissue/reverse now inherit
the stricter `_forbid_non_admin` via the `_transition` helper — CA/SA only,
because sending allocates the gapless number and emails the customer (a
company act, not a building act) — **and** each of those four state-machine
functions **independently re-checks** `is_invoice_admin`
(`invoicing/permissions.py`, stable code `invoice_admin_only`). That double
gate is deliberate defence in depth — keep both. A BUILDING_MANAGER keeps the
building-level half: generate, preview, draft meta/lines, delete-draft, PDF
and the lists, all still on the operator gate. The PDF endpoint
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

## B.11 The document is FROZEN at SEND (Sprint 180)
Until Sprint 180 the invoice PDF was **re-rendered from live data on every
download** (`views.py` called `render_invoice_pdf` on each request) and the
model carried **no file field and no snapshot field at all**. A SENT
invoice's document could therefore render differently later if anything
behind it changed — a renamed customer, a relabelled department, a changed
brand slug. An invoice is a legal artefact, not a view.

**The rule: snapshot it, save it, never recompute.**

* **Frozen at SEND**, inside `send_invoice`'s existing `transaction.atomic()`
  block. SEND is where the gapless number is assigned (§B.2) and where the
  invoice becomes immutable (§B.4), so it is the first moment the document is
  finished and the last at which it still describes what was decided. The
  freeze shares that transaction: if the file or its digest cannot be
  written, the send fails with it — "SENT with no frozen document" is exactly
  the state this removes and must not be reachable through the happy path.
* **A DRAFT keeps rendering fresh.** So does an ISSUED-but-unsent invoice. A
  draft is still changing and its preview is taken from it. Freezing at issue
  was considered and rejected; do not re-open it.
* **Four fields** on `Invoice`: `pdf_file` (the bytes), `pdf_frozen_at`,
  `pdf_sha256` (the integrity witness) and `pdf_page_count`. Migration
  `invoicing/0006_sprint180_frozen_invoice_pdf`. Additive and nullable; it
  backfills nothing.
* **Invoices sent before the field existed** freeze **lazily on first
  access** (`invoice_pdf.invoice_pdf_bytes`, row-locked and re-checked under
  the lock so two concurrent downloads cannot both write), **and** can be
  done deliberately in bulk with `python manage.py freeze_invoice_pdfs`
  (`--company`, `--limit`, `--dry-run`). The backfill is an OPERATIONAL
  command, not a data migration: rendering every historic invoice inside a
  deploy is the wrong place for real work, and a half-failed migration fails
  the deploy with it.
* **Nothing is ever re-frozen.** `freeze_invoice_pdf` returns untouched an
  invoice that already has a file, and the command has no `--force`. The
  frozen document IS the artefact.

`pdf_frozen_at` and `pdf_page_count` are exposed on the PROVIDER serializer
(so an operator can see which documents are frozen and how long they are).
`pdf_sha256` and `pdf_file` are not exposed anywhere: the digest is an
integrity witness for tests and audit, and the storage path is internal.

## B.12 The invoice is a summary page plus a SPECIFICATION annex (Sprint 180)
The owner showed how his father's invoices are actually assembled: **page 1
is the summary** — one line, "3 meerwerken - Zie bijlage voor specificatie",
with the total — and **from page 2 onward the per-building extra-works detail
is appended, page after page**. An invoice can run to eight pages. That was
being stapled together by hand.

```
Page 1   FACTUUR - samenvatting
         "3 meerwerken - Zie bijlage voor specificatie"   157,40 + 21% = 190,45
Page 2+  BIJLAGE - specificatie, grouped building -> department -> work type
         #  Titel                                Week  Uitgevoerd    Excl. BTW
         1  Louis + Atrium // B.3                 27   03-07-2026       110,18
         2  The Sheryl                            28   07-07-2026        31,48
```

* Built in `backend/invoicing/annex.py`, on the SAME `fpdf2` instance and the
  same shared brand helpers (`config/pdf_branding.py`) — **no new PDF
  library**, which the repo forbids.
* `build_annex(invoice)` returns plain dataclasses, so the grouping is
  testable as data with no PDF involved. Page 1's count and the annex's rows
  are read from the SAME `Annex`, so they cannot drift.
* **Every appended page repeats the branded header and the column headers.**
  A page that arrives on its own must still say what it is.
* Amounts are read from `invoice.lines` and never re-derived from the extra
  works: the invoice is the source of truth for its own money.
* Row numbering is continuous across the whole annex; an unset department or
  work type sorts LAST within its building rather than first.
* **This REPLACED** the previous fixed page 2, a flat per-line table carrying
  quantity / unit price / VAT% columns. The owner's own invoices do not carry
  those — the specification says what was done, when, and the amount
  excluding VAT, and the VAT is summarised once on page 1. Keeping both would
  print the same money twice in two shapes.
* **A credit note has no work to list.** `reverse_invoice` mirrors every line
  with `extra_work=None` (§B.4), so a reversal's annex **references the
  original invoice number** instead of inventing line data that is not there.
* The reference system's reports carry a "members" section. The owner has
  said explicitly to ignore it; it is not part of this.

**Privacy.** The annex reads nothing from an Extra Work request except its
building / department / work-type NAMES, all three of which the customer
serializer already exposes. `test_sprint180_frozen_pdf_and_annex.py` asserts
the absence of an EW description and an internal cost note on **every page**
of a multi-page document, not only page 1 — an annex that leaks onto page 4
is the same failure as leaking on page 1, and a page-1-only check will not
see it.
