# Addendum C — Contracts (Sprint 160)

**Status:** shipped in Sprint 160 (branch `feat/sprint-160-contracts`).
**Hierarchy:** an Addendum, so it **wins over the base Source of Truth**
for the items it covers. Where this doc and the code disagree, the code
is the truth — report the drift.

Companion to
[Addendum B — invoicing](sot-addendum-b-invoicing.md). Addendum B
describes how an invoice is raised, numbered and corrected. This one
describes the **recurring agreement that says an invoice is owed at
all**, and stops one step short of raising it.

---

## C.0 What a contract is, in plain words

A contract is what a customer has agreed to pay on a recurring basis:
which locations are covered, what projects are done there, how many
hours those are budgeted for, what they cost, and on what rhythm the
invoices go out.

Before Sprint 160 the system held **no contract entity at all**.
`Customer.contract_pdf` existed — an informational file with zero
behavioural effect, whose UI Sprint 155 removed — and the word appeared
in a few invoicing comments. That is all it was.

---

## C.1 Three decisions, settled with the owner before the build

These were put to the owner and answered. They are not open.

1. **Contract invoices are REAL invoices**, not merely a forecast. The
   billing settings only mean something if invoices actually get
   produced. Sprint 160 builds the FORECAST; **turning a due forecast
   row into a real `Invoice` is Sprint 158's**, and the forecast is
   deliberately shaped so that step is small (see C.5).
2. **A contract carries its OWN prices.** It does **not** read
   `extra_work.CustomerServicePrice`, and must never learn to. Extra
   Work continues to price through `extra_work.pricing.resolve_price`
   exactly as before and was not touched by this sprint.

   Two price sources, one clear division: **contract prices govern the
   contract, agreed prices govern extra work.** They look similar (both
   are per-customer agreed money with a validity window) and are not
   the same fact — merging them would make a contract's agreed monthly
   fee mutable by a catalog edit. The division is written into the
   model docstrings so the next person does not "unify" them.
3. **Contract hours will be compared against worked hours**
   (`timesheets.TimeEntry`). Not in Sprint 160 — Sprint 159 — but the
   hours field is shaped so the comparison is possible without a schema
   change: `ContractLine.hours` is a per-billing-period budget and
   carries an optional `building`, so the later comparison has a period
   basis and something to group by.

---

## C.2 The model — `backend/contracts/`

An independent app, in the sense `timesheets` is: no FK into and no
import from `extra_work`, `tickets` or `invoicing`.

| Model | What it is |
| --- | --- |
| `ContractType` | Per-company catalog of contract kinds ("Schoonmaak", "Machines"). NOT a hardcoded enum — same architecture as `timesheets.HourType`, including the case/whitespace-insensitive per-company unique name created WITH the table. |
| `Contract` | The header: company, customer, locations, dates, status, and the five billing settings. |
| `ContractBuilding` | The M:N to `buildings.Building` ("Locations"). An explicit through-model, so the audit layer has a row to register (the `ContactBuildingLink` precedent). |
| `ContractRevision` | A **version** of the contract's agreed scope, effective from a date. See C.3. |
| `ContractLine` | One project on a REVISION: name, optional building, hours, m², amount, VAT. |
| `ContractNumberSequence` | The per-(company, year) counter behind gapless numbering. |

### Numbering

`CNT-YYYY-NNNN`, gapless per (company, year), allocated by
`contracts/numbering.py` with a `select_for_update` on a dedicated
counter row. This **mirrors the SHAPE of `invoicing/numbering.py` and
imports nothing from it** — a contract number is not an invoice number,
and sharing an allocator would make the two sequences one.

Two deliberate differences from invoice numbering:

* **Assigned at CREATE, not at a later transition.** An invoice gets its
  number at SEND because a number is a claim on a document that has left
  the building; a draft contract still has to be referred to by number.
* **The year is the `start_date` year**, not the allocation year. A 2027
  contract drafted in December 2026 is a 2027 contract.

### Status cannot contradict the dates

`Contract.lifecycle` stores only `DRAFT` / `ACTIVE` / `CANCELLED`, and a
**CHECK constraint (`contract_lifecycle_is_storable`) makes EXPIRED
unstorable.** The status an operator sees is derived by
`Contract.status()`:

* CANCELLED or DRAFT — the operator's own statement, and it wins over the
  calendar. A cancelled contract does not become "expired" when its end
  date passes; a draft never silently becomes active.
* otherwise EXPIRED when `end_date` is in the past, else ACTIVE. An
  open-ended contract (`end_date` NULL) never expires.

So the two cannot disagree — not by convention, but because the
contradiction is unrepresentable in the table.

### Money

`Decimal` throughout, quantized HALF_UP to 2dp, never through a float.
`ContractLine.amount` and `.hours` are per **billing period** (a
quarterly contract's line amount is a quarter's money); the monthly and
yearly figures are normalised from `billing_period` server-side, and are
annotated on the queryset rather than stored. **No total is stored
anywhere** — a stored total is a second copy of a number that already
exists, and the copy is what drifts.

---

## C.3 Revisions — a version, NOT an audit log

The distinction is load-bearing, and getting it wrong was a real risk in
the design.

* `AuditLog` answers **"who changed this field, and when"** — an
  after-the-fact record of an edit.
* A revision answers **"what is this contract's agreed scope as of a
  date"** — a business fact, with money attached, that may have a FUTURE
  effective date and that invoices are computed against.

AuditLog cannot serve the second question and must not be used for it.
(Revisions are *additionally* audited, like every other model here.)

Rules:

* **The lines hang off the REVISION, not off the contract.** That is what
  makes a revision mean anything: raising a price creates a new revision
  effective next month, and last month's invoices still reflect what was
  agreed then.
* **Creating a contract creates its first revision automatically**,
  labelled "Oorspronkelijk contract" / "Initial contract", effective from
  the contract's start date. A contract is never revision-less, and the
  API refuses to delete the last one.
* **The active revision is DERIVED** — `contracts/revisions.py`, the
  latest `effective_from` at or before the date, ties broken by `-id`.
  There is no `is_active` flag, for the same reason there is no stored
  EXPIRED.
* **A revision locks the moment its effective date arrives.** Its label,
  date and lines all become read-only, and a correction is a NEW
  revision — exactly as a SENT invoice is corrected by reversal rather
  than by editing. A future-dated revision stays fully editable, which
  is the point of being able to author one ahead of time.
* **A date before the first revision resolves to `None`**, not to the
  first revision. The contract had no agreed scope before it was agreed,
  and a forecast for such a date must produce nothing rather than borrow
  the future's prices.

The resolution discipline is copied from
`extra_work.pricing.resolve_price` over `CustomerServicePrice`'s validity
windows — the same problem, solved once already in this codebase — while
importing nothing from it.

**`display_revision` vs `active_revision`.** The UI needs a second,
deliberately more generous resolver: a contract signed today to start in
March has nothing in force *today*, and its header card must still say
what it is worth. `display_revision` falls back to the earliest revision;
`active_revision` never does. Keeping them apart is what lets the strict
one stay strict, and `contracts/billing.py` uses only the strict one.

---

## C.4 Permissions and scoping

| Role | Contracts |
| --- | --- |
| SUPER_ADMIN | Everything, in the company they are working in (the Sprint 149 `?company=` model). |
| COMPANY_ADMIN | Everything within their own company. |
| BUILDING_MANAGER | **Read only**, and only contracts covering a building they manage. |
| STAFF | **No access.** Negotiated prices are not field-staff data, and unlike hours there is no "your own" subset that would make sense. |
| CUSTOMER_* | **No access, ever.** A contract carries the customer's negotiated prices; this sprint opens no customer-facing surface. Tested on every endpoint. |

`contracts/scope.py` mirrors the SHAPE of `timesheets/scope.py` and
imports nothing from it. Every serializer validation lookup (`customer`,
`buildings`, `contract_type`) resolves through a SCOPED queryset, so an
out-of-scope id fails as `does_not_exist` — **byte-identical to a
fictional id** (H-1). The DRF default message was hardened to drop the
echoed pk so that equality is literal rather than something a test has to
normalise for.

The one deliberate exception: a SUPER_ADMIN naming a company-B building
on a company-A contract gets a distinct `building_cross_company` 400.
They can already see both companies, so that is a mistake worth
reporting, not an existence leak — and nobody else reaches the branch.

---

## C.5 The Invoice Preview — a calculation, not a write

`contracts/billing.py` is a **pure function** over a contract and a
year. It writes nothing: no `Invoice`, no `InvoiceLine`, no state, and
there is no POST route on the endpoint. That is what makes Sprint 158 a
small step rather than a rewrite.

The rules it implements:

* **Periods are calendar-aligned.** MONTHLY bills calendar months,
  QUARTERLY bills Jan–Mar / Apr–Jun / …, YEARLY bills the calendar year.
  The first period is the calendar period *containing* `start_date`.
* **Proration is by day count**, and `start_proration` governs BOTH ends:
  a contract starting mid-period bills a part period first, one ending
  mid-period bills a part period last. Off means every period bills in
  full.
* **A period's money comes from the revision active at the period
  START.** A revision taking effect mid-period therefore governs from the
  next period — splitting a period at a revision boundary would produce
  two invoices for one billing period, which no billing setting can
  express.
* **Invoice date.** ADVANCE dates it on `billing_day` of the period's
  first month; ARREARS on `billing_day` of the month after the period
  ends. The FIRST invoice is never dated before the contract exists.
* **`billing_day` is capped at 1..28** so the day exists in every month —
  the same reasoning `Customer.invoice_day_of_month` already uses.
* **The preview lists the invoices still to come.** It excludes the FIRST
  invoice, the one already raised when the contract was signed —
  implemented as `invoice_date > first_invoice_date`. That rule was
  chosen over "on or after today" because it is a property of the
  contract's own dates: it gives the same answer on every run, where a
  today-relative rule would silently shrink the preview as the year
  progressed and could not be tested without freezing the clock.
* **Yearly is NOT monthly × 12.** `yearly_amount` is the sum of the
  ACTUAL period amounts scheduled in the year, *including* that excluded
  first one — which is exactly why it is larger than the caption's total
  and why it differs from twelve equal months whenever a part period was
  prorated. With proration off the two agree. Both directions are
  asserted in `contracts/tests/test_billing.py`.

Useful for Sprint 158, already verified: `InvoiceLine.extra_work` is
NULLABLE and its docstring already anticipates a hand-added free-text
line, so a contract invoice fits the existing schema without changing it.

---

## C.6 Surfaces

* `/admin/contracts` — the list. Stat tiles over the current filters;
  search / customer / building / status / type filters with a
  filter-is-on line that clears in one click; three views (List,
  Customer Summary, Building Summary) derived from ONE fetch; Prices ⇄
  Hours and Monthly ⇄ Yearly toggles; per-project columns that are
  dynamic per tenant and **bounded** — the top six by value, with the
  rest folded into "Other" and the folded count stated.
* `/admin/contracts/:id` — four tabs (General Info, Projects, Billing,
  Revision History), an Edit Contract modal, and the Invoice Preview on
  the Billing tab with its year stepper.
* Every mutation is behind `useEditMode` or an explicit Edit button.
* i18n lives in its **own namespace** (`i18n/{nl,en}/contracts.json`),
  not in `common.json`.

### Known limits, recorded rather than dropped

* **The three views group the FETCHED PAGE, not the whole result set.**
  With 25 contracts per page the summaries describe that page. Making
  them tenant-wide needs a server-side aggregate, which is a deliberate
  next step rather than a client-side loop over every page.
* **In the Building Summary a contract covering three buildings appears
  under each of them**, so the group totals sum to more than the tenant
  total. That is the correct answer for a per-location reading, not a
  double count to fix.
* **The Projects tab is read-only on a running contract**, because its
  revision is in force. Changing a price is the "New revision" button.
  This is the feature, not a limitation to work around.
