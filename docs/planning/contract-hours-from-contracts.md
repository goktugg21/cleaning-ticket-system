# Contract hours, pulled from a contract — what it would take

Sprint 179B §6. **Investigation only. No code was written for this.** The
owner asked: *the source is only chosen while entering hours. If contract
hour data is pulled from somewhere, let it be pulled AND stay editable.*

Everything below was read from the code at `56c0740`.

---

## 1. What exists today

**`timesheets.ContractHours` is not a contract.** It is the hours a worker
is contracted for: a standing weekly pattern — seven weekday decimals —
for one `(employee, building, hour_type)`, in force from `valid_from`
until `valid_to`. Its docstring
([backend/timesheets/models.py:658](../../backend/timesheets/models.py))
says in as many words that the word "contract" here is the operator's word
for a standing agreement and that there is **deliberately no foreign key**
to `contracts.Contract`: `timesheets` must keep working for a company that
uses nothing else, and the join belongs in `reports`, the app allowed to
read both.

The import graph agrees with the docstring. `contracts` imports nothing
from `timesheets`; `timesheets` imports nothing from `contracts`; there is
no cross-app foreign key in either direction, in either app's migrations.

**Every `ContractHours` row is typed in by hand**, through exactly two
write paths, both in
[backend/timesheets/serializers_contract_hours.py](../../backend/timesheets/serializers_contract_hours.py):

- `POST /api/timesheets/contract-hours/` — one row;
- `POST /api/timesheets/contract-hours/bulk/` — the **Bulk assignment**
  dialog. The operator picks employees, buildings, a `valid_from` and one
  optional work type, fills a week grid, and the dialog folds the grid's
  dated cells back into weekday columns. Re-running it skips a row that
  already exists for `(employee, building, hour_type, valid_from)`.

No management command, no seeder, no admin action, no data migration
creates one. **Nothing in the backend derives an hours figure from a
`Contract` into `ContractHours`.**

**Does a contract even carry hours?** `Contract` itself does not — no
hours, no rate, no schedule, no employee. Its only cadence fields
(`billing_period`, `billing_day`, `billing_type`) are invoicing cadence.
The hours live one level down, on `ContractLine.hours`
([backend/contracts/models.py:593](../../backend/contracts/models.py)):
"budgeted hours for ONE billing period of this contract", with an
**optional** building and no employee.

**The join already exists, in the read direction.**
[backend/reports/hours_comparison.py](../../backend/reports/hours_comparison.py)
turns `ContractLine.hours` into a per-building monthly target
(`line.hours / MONTHS_PER_PERIOD[billing_period]`) and compares it against
worked `TimeEntry` hours. Its docstring already refuses to go further:
a contract says "40 hours a month at this building", never "40 hours of
Ahmet", so presenting a per-employee contracted figure "would mean
inventing an allocation nobody agreed".

---

## 2. What it would cost, and which shape I would choose

The two grains do not line up:

| | grain |
|---|---|
| `ContractLine.hours` | (revision, optional building) × **billing period** |
| `ContractHours` | (employee, optional building, hour type) × **weekday** × validity window |

Going from the first to the second requires inventing three facts no
contract states: **which employee**, **which weekday split**, and **which
hour type**. That is not a missing feature; it is missing information.

**Two shapes are possible without an FK across the module boundary.**

**(a) A read-side derivation in `reports`.** Cheap — it is essentially
already built. It cannot produce editable rows, because there is nothing
to edit: the number is recomputed from the contract on every read. It
answers "agreed vs worked per building", which the Hours Comparison report
already answers. It does not answer the owner's request, which is about
rows an operator can then correct.

**(b) A generator that writes ordinary `ContractHours` rows — my
recommendation.** A new endpoint in `reports/` (the app allowed to read
both) takes a contract, its active revision's lines and the operator's
choice of **which employees** and **which weekday split**, and returns a
*suggested* set of rows. The operator sees them in the existing Bulk
assignment grid, edits them, and presses Save — which posts to the
existing `contract-hours/bulk/` endpoint. Nothing about the write path,
the audit trail, the DRAFT → SAVED → APPROVED state machine or the
scoping changes. `timesheets` gains no import. The suggestion is a
starting point, and the row is an ordinary hand-made row from the moment
it is saved — which is exactly "pulled AND still editable".

Rough size: one read endpoint plus its scoping and `assertNumQueries`
tests; a contract picker and a weekday-split control in
`ContractHoursBulkDialog`; the allocation rule (per-employee split of a
line's per-period hours) written down once, with tests. Call it one
sprint, not more — most of the machinery it needs already exists.

**Why not (a)+(b) as a stored derived field:** a stored figure that
silently changes when a contract revision lands would rewrite an agreement
an operator already approved. The versioning rule on `ContractHours` is
explicit that changing an agreement writes a NEW row from a date and never
edits history, "because last month's comparison must keep saying what it
said last month".

---

## 3. What would break, and the company that has no contracts

- **Nothing breaks for a tenant that uses hours but not contracts.** The
  generator is an extra button. With no contracts it offers nothing, and
  every existing tab — Contract hours, Contract approval, the Worker Hour
  Report's `Contr. uren` column — is fed by `ContractHours` alone and is
  unaffected. That is exactly the property the no-FK rule was protecting,
  and shape (b) keeps it.
- **The allocation is a decision, not a calculation.** Splitting a line's
  hours across employees and weekdays needs a stated rule (equal split?
  operator-typed?). Whatever is chosen will be wrong for somebody, which
  is why it must land in an editable grid rather than straight in the
  database.
- **Two pre-existing hazards this work would touch.** First, there is
  **no database uniqueness** on `(employee, building, hour_type,
  valid_from)` — the bulk endpoint's dedupe is a Python check-then-act,
  and it is not company-scoped. A generator that can produce many rows at
  once makes that a likelier collision. Second, the per-period hours basis
  is applied **three different ways** today: divided by
  `MONTHS_PER_PERIOD` in `reports/hours_comparison.py`, left unscaled in
  `frontend/src/pages/admin/contracts/contractTables.ts` (deliberately,
  with a comment), and multiplied by periods-per-year in
  `ContractDetailPage.tsx`'s "hours per year" field. A generator has to
  pick one, and the other two should be reconciled in the same sprint.

**The owner decides.** This is not built.
