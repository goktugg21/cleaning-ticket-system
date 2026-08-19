# The Osius reference system — master connection map

**What this is.** A read-only investigation of a third-party reference system (Laravel 12
API + React SPA) belonging to the owner's father, mapped so that its *logic* can be
understood. Nothing here was modified. This document is the deliverable; reports 01–09
are the evidence beneath it.

**Scope of the evidence.** Two repositories were read in full
(`crm-acl_srv-v1.1-review`, `crm-web`) and the live API at `dev-api.osius.nl` was queried
read-only. Ten agents produced reports 01–09; a live-data pass (V1) tested 56 tier-1
claims and a contradiction sweep (V2) ruled on 16 disputes. Where agents disagreed, the
ruling and its quoted source line are in `09-verification.md` PART 2.

**How to read the labels.** `CODE` = a file and line that was read. `DATA` = a live API
response. `INFERRED` = a reading that fits the evidence but was not directly observed;
every one says what would confirm it.

**One vocabulary note.** Their `Product` is our `Service`. Their names are kept
throughout. Every place the two concepts meet money is flagged.

---

# PART 1 — THE LOGIC, IN PLAIN ENGLISH

## 1.1 The one-paragraph version

An Extra Work is a job on a building. A person creates it, plans it, marks it complete,
approves it, archives it, and then — in a separate screen, by hand — folds it into an
invoice. Every one of those steps is a person pressing a button. **Nothing in this system
happens by itself.** There is no scheduler, no reminder, no ageing, no escalation, and no
automatic invoicing. There is also no state machine: any status can be set from any other,
in any direction, by anyone holding one permission bit. The invoice, when it is finally
created, carries only the *product* money — the entire hours-and-labour subsystem is
computed, displayed, and then discarded at the invoice boundary.

## 1.2 The five facts that govern everything else

**1. There is no state machine.** `status_id` is a plain foreign key validated only by
`exists:t_ticket_status,id`. No transition table, no guard, no from-state check, no role
condition. Any status → any status, forwards or backwards.
`CODE ExtraWorksController.php:3624-3629`

**2. Status 8 is the only gate into billing, and status 9 is the only billed flag.**
Invoicing selects `where('status_id', 8)`; creating an invoice stamps its works to 9;
un-invoicing puts them back to 8. Nothing else records that a work was billed.
`CODE InvoiceController.php:309, :152, :265-271`

**3. Nothing is time-driven.** No scheduler is defined (no `withSchedule()`, no
`Kernel.php`, stock `routes/console.php`), and **no `schedule:run` target exists anywhere
in either repository** — not in the systemd units, not in the deploy scripts. No date on
an Extra Work is ever compared to the clock inside the Extra Work area.

**4. Permissions are decided by your role alone.** The middleware named
`ucb.permission` — "user-customer-building" — never looks at user-customer-building data.
It maps an action word to a bit and asks whether your `role_id` holds that bit. There are
no Laravel Policies and no Gates in the codebase.

**5. The connection between a work and its invoice runs one way only.** The column that
looks like the forward link, `extra_works.invoice_id`, is NULL on every invoiced work in
live data. The link that works is `invoice_items.extra_work_id`.

## 1.3 What the system does well, stated plainly

Three things in this system are correct and deliberate, and are worth separating from the
defects:

- **The price snapshot.** Product name, price, tax rate, unit and category are copied *by
  value* onto the work's line at add-time. An old work never silently re-prices when the
  catalogue changes. This is the right decision, implemented consistently.
- **The activity log's intent.** `extra_work_activities` records status changes, date
  changes and approvals with the acting user — when the write path goes through Eloquent.
- **The draft/publish idea for attachments.** Photos are staged during completion and
  published on approval. The mechanism exists and fires; its problems are in *who can see
  drafts* and *which path skips the publish*, not in the concept.

---

# PART 2 — THE SINGLE GRAPH

Centred on Extra Work and Invoicing. `──>` is a real, live pointer. `--✗-->` is a pointer
that exists in the schema but is never populated or never read. Live row counts are from
the API on the date of investigation.

```
                        t_ticket_status  (SHARED WITH TICKETS AND WITH ExtraWorkV2)
                        1 new · 2 in_progress · 3 resolved · 4 closed
                        5 internal_approval · 6 customer_approval · 7 invoiced_v2
                        8 archived("Voltooid") · 9 invoiced
                                    ▲
                                    │ status_id  (validated ONLY by exists:)
                                    │
   customers ──┐                    │
   buildings ──┼──> EXTRA_WORKS (v1) ─────┬──> extra_work_products ──> customer_products
   departments ┤    ~76 live rows         │      (PRICE SNAPSHOTTED BY VALUE)   │
   works_types ┘         │  │  │  │       │                                     │
                         │  │  │  │       └──> extra_work_employee_hours        │
                         │  │  │  │              └──> employees ──> employee_hourly_rates
                         │  │  │  │                   (rate snapshotted; 35/40 have none)
                         │  │  │  │
                         │  │  │  └──> extra_works_attachments (is_draft, is_pre_file)
                         │  │  └─────> extra_work_comments ──> extra_work_comment_reads
                         │  └────────> extra_work_activities   (the audit trail)
                         │
                         │  extra_works.invoice_id     --✗--> invoices   (NULL on all 37)
                         │  extra_works.invoice_date   --✗-->            (NULL on all 37)
                         │
                         └──< invoice_items.extra_work_id ──> INVOICES   (3 live)
                                    │      THE ONLY REAL LINK             │
                                    │      (reverse = hasOneThrough)      │
                                    │                                     │
                                    └──> invoiceable_items --✗--> (0 extra-work rows;
                                          13 rows, all type `project`)     the 13 are
                                                                          unrelated to EW

   ─────────────────── the two other "invoiced" mechanisms, both dormant ───────────────
   EXTRA_WORKS_V2 ──> invoiceable_items ──> extra_work_v2_invoices   (Path B: 0 EW rows)
   extra_work_v2_period_products.invoice_number  = a FREE-TEXT STRING, no foreign key,
                                                   nothing checks the invoice exists (Path C)

   ─────────────────── things that point AT the spine and do nothing ──────────────────
   grades_inspections.extra_work_id   --✗-->  real FK, fillable, cast, belongsTo … never assigned
   ExtraWork::tasks() -> TicketTask   --✗-->  class deleted, table dropped; calling it FATALS
   portal_extra_works (SQL view)      --✗-->  selects ew.invoice_id; nothing in PHP reads the view
```

## 2.1 What is NOT in this graph, and that is the finding

- **No scheduler node.** Nothing enters the graph from a clock.
- **No labour edge into `invoice_items`.** `extra_work_employee_hours` reaches display
  totals and reports, and stops there.
- **No credit note, no reversal, no negative line, no invoice-references-invoice.**
- **No period edge.** Nothing computes which works belong to which billing window.
- **No escalation edge.** No notification is addressed to a manager because someone else
  failed to act.

---

# PART 3 — THE FULL LIFECYCLE, WITH EVERY SERVER-SIDE SIDE EFFECT NAMED

The column that matters is the third: **what the server writes that the client never
sent.** This is the heart of the system's behaviour.

| # | Step | Endpoint | Status | Server stamps, unasked |
|---|---|---|---|---|
| 1 | Create | `POST /admin/extra-works` | → 1 | `created_by` = **"Name (Role)" as a string**, not a user id |
| 2 | Plan | `PUT /admin/extra-works/{id}` | 1 → 2 | `planed_by` = "Name (Role)"; `planed_at` = `now()` if absent from body |
| 3 | Complete | `PUT /admin/extra-works/{id}` | 2 → 3 | `completed_by`; `completed_at` = `now()` if absent |
| 4 | Approve | `PUT /admin/extra-works/{id}` | 3 → 4 | `approved_by`; `approved_at` = `now()` if absent; **AND every draft attachment is flipped to published** |
| 5 | Archive | `POST /admin/extra-works/{id}/archive/approve` | any → 8 | `archive_approved_*`, back-fills `archive_requested_*`, clears `archive_rejected_*`. **Not logged as a status change.** Writes 8 *whatever the prior status*, including 9 |
| 6 | Invoice | `POST /admin/invoices` | 8 → 9 | one `invoice_items` row per work; `status_id = 9`. **Does NOT write `invoice_id`/`invoice_date` on the work** |
| 7 | Send | `POST /admin/invoices/{id}/send` | — | invoice only: `status='sent'`, `pdf_path`, `pdf_generated_at`, `sent_at`. **Touches no work** |

**The stamping is keyed off the status number in the request body, not off a transition.**
The dedicated `PUT /{id}/status` endpoint stamps *nothing at all* — it writes `status_id`
and returns. `CODE ExtraWorksController.php:1191-1241 vs :3634-3656`

## 3.1 Three consequences of that design

**Revert destroys the timestamp it is not reverting.** There is no revert endpoint —
the SPA issues an ordinary `PUT` with the previous status number and some explicit nulls.
Reverting 4 → 3 sends `status_id: 3` without a `completed_at`, so the server re-stamps
`completed_at = now()`. Undoing an *approval* destroys the original *completion* time.

**The group path skips customer approval entirely.** The single-record path is
3 → 4 → 8 and publishes draft photos at 4. The group bar's "Goedkeuren" jumps **3 → 8
directly**, so those works enter the billing pool with `approved_at = NULL` and their
draft photos still unpublished. `DATA` all eight members of group 17 are at status 8 with
`approved_at` null.

**Bulk operations are invisible.** The four bulk endpoints use query-builder mass
`update()`, which fires no Eloquent events — so no observer, no system comment, no
broadcast, no FCM, no activity row. A work can move between statuses leaving no trace.

## 3.2 The five doors out of status 9, and the two that are broken

| Door | Guard | Effect on the work | Effect on the invoice |
|---|---|---|---|
| Delete the invoice | draft only | → 8, links cleared | hard-deleted |
| Remove a work from the invoice | draft only | → 8, links cleared | line deleted; empty invoice auto-deleted |
| Delete an invoice line | draft only | → 8, links cleared | as above |
| **Cancel the invoice** | sent only | **NOTHING** | cancelled |
| **`PUT /{id}/status`** | **none** | any status at all | **NOTHING** |

> **Cancelling a sent invoice permanently destroys billability.** The handler updates the
> invoice row and nothing else. The works stay at 9, keep lines pointing at a cancelled
> invoice, never return to the status-8 pool, and can never be re-billed through the UI.
> (The V2 subsystem's cancel path *does* release its items. The live v1 system does not.)

And because status 9 is the only billed flag, **any user holding `extra_works,update` —
which includes the customer and employee roles — can un-bill an invoiced work, or mark an
unbilled one invoiced, by sending one integer.** The `/status` and `/archive/*` variants
load the record with a bare `findOrFail` and are not row-scoped, so this can be done to a
work belonging to a customer the actor has no relationship with.

`DATA` Live proof that this is not theoretical: six works sit at status 9 with no invoice
line and no invoice at all (476, 444, 440, 439, 438, 437), three of them carrying an
`invoice_date` with no invoice behind it. And work 448 has been invoiced and un-invoiced
**eight times**.

---

# PART 4 — THE MONEY PATH, END TO END

## 4.1 How a line gets its price

`customer_products` (per-customer catalogue) → copied **by value** onto
`extra_work_products` at add-time: `name`, `price`, `tax_rate`, `unit_id`, `category_id`,
`quantity`. `customer_product_id` is stored but only renders a link — no total, report or
invoice ever follows it back.

`DATA` Work 476's line reads `"Extraschoonmaak" / 45.18`; customer product 105 today reads
`"Opleverschoonmaak" / 37.020`. Both name and price changed after the work was priced and
the work kept the old ones. **Old works never re-price** — which also means changing a
catalogue price cannot correct a mistake on an existing work. Only hand-editing the line can.

There is a dated price-version book (`customer_product_versions`, `customer_product_prices`)
and it is **invisible to extra works and to invoicing**. `product_price_history` is a dead
table with no writer anywhere.

## 4.2 The work total is never stored — it is computed six different ways

| # | Where | Rounds | Labour? | VAT? |
|---|---|---|---|---|
| 1 | `total_products_cost` | per line | **no** | excluded |
| 2 | `total_cost` | per line | **yes** | excluded |
| 3 | list view (`transformModelData`) | per line *and* per line-tax | no | included |
| 4 | detail / approval modal (`calculateFinancialSummary`) | on the total | no | included |
| 5 | `priceBreakdown` endpoint | on the total | **yes** | flat 21% |
| 6 | `ReportsController` (10 methods) | **not at all** | no | excluded |

Formulas 3 and 4 can differ by cents on the same record. There is no single rounding policy.

## 4.3 Where the money is lost — the invoice boundary

**The invoice takes formula #1.** `CODE InvoiceController.php:141, :609`
```php
'amount'   => $work->total_products_cost ?? 0, // Only products, not labor
'tax_rate' => 0.21,                            // Default 21% KDV
```

Three separate losses happen on those two lines:

- **Labour is discarded.** The comment says so explicitly. Everything the hours subsystem
  computes stops here.
- **The real VAT rate is discarded.** VAT is correctly per-line on the work — live data has
  a genuine 9% product, correctly carried onto work 448's line — and the invoice overwrites
  every line with the literal `0.21`.
- **Multi-product works collapse wrongly.** `quantity` and `unit_name` are taken from
  `$work->products->first()` only, while `amount` is the total of *all* products. A
  three-product work becomes one line whose amount covers three products and whose
  quantity describes one.

There is also a **units mismatch nothing normalises**: `products`, `customer_products`,
`extra_work_products`, `invoiceable_items` all store VAT as a percent (`21.00`), while
`invoice_items` and `invoices.summary_tax_rate` store a fraction (`0.2100`). Exactly one
line of code converts between them, on a path v1 never uses.

## 4.4 The hours chain, and why it is decorative

Labour cost lives only on `extra_work_employee_hours.total_cost`, written by a model
`saving` hook as `round(hours × hourly_rate × overtime_multiplier, 2)`.

- `hourly_rate` is **snapshotted at row creation**; the update endpoint cannot change it.
- `overtime_multiplier` is read live at save then discarded — so editing a multiplier later
  shows the **new** multiplier beside the **old** cost.
- **No rate ⇒ the snapshot is `0`, silently.** `DATA` 35 of 40 live employees have no
  hourly rate at all. Every hour booked for them is free.

Nothing caps hours. All three guards are dead: `canDistributeHours()` has exactly one
occurrence in both repositories — its own definition; `validateTotalHours()` is never
called, with the epitaph `// Hours validation removed per user request` in the model's
boot; and `getRemainingHours()` is **structurally always zero**, because its expression
`$this->hours ?? $this->hours_worked ?? $this->total_hours ?? 0` starts with a property
that does not exist on the model, falls through `hours_worked` (NULL on every live record)
and lands on an accessor returning the distributed hours themselves — so it computes
`max(0, distributed − distributed)`. Wiring `canDistributeHours()` up would refuse *every*
distribution.

Hours also go invisible while still counting: the grid is built from worker assignments
with hours matched on `employee_id`, so hours belonging to a removed worker vanish from the
screen but stay in every total. `DATA` Work 474 shows `distributed_hours: 13.5`,
`total_labor_cost: 270`, `assigned_workers: []` — an empty grid with EUR 270 behind it.

**The chain:** hours are booked with no cap → priced from a snapshot that is silently zero
for 87% of employees → sometimes attached to an invisible worker → summed into two display
formulas → **and then never reach the invoice.**

## 4.5 Three totals on one invoice

| Consumer | Number shown |
|---|---|
| `invoices.total_amount` (the database) | `Σ(amount × quantity) + tax` — **ignores `summary_price` entirely** |
| PDF page 1 ("Overzicht") | `summary_price` if set, else `Σ(amount × quantity)`, minus discount, × a weighted-average tax rate |
| PDF page 2 ("SPECIFICATIE") | `Σ(amount × quantity)` per line — discount **not** applied, `summary_price` **not** applied |

A hand-edited invoice total wins on page 1 of the document the customer receives, loses on
page 2 of that same document, and never reaches the database. The `update()` endpoint does
not recalculate `subtotal`/`tax_amount`/`total_amount` after writing `summary_price`.

*(V1 measured the rendered PDF at **three** pages, not two — `Pagina 3/3`. The page-1
versus page-2 divergence above is established from the template; the content of the third
page was not separately mapped. See PART 7.)*

## 4.6 Invoice numbering — three regimes, none safe

1. **The v1 EW path takes the number from the client.** `'invoice_number' =>
   'required|string|unique:invoices,invoice_number'`. The server never generates it, and
   `unique` is a check-then-insert, so two concurrent requests can both pass validation.
2. **`createFromInvoiceableItems` and the installment path** call `generateInvoiceNumber()`,
   an application-side `max()+1` (`orderByDesc('invoice_number')`, strip prefix, cast, add
   one). Not a database sequence — it collides under concurrency.
3. **`ExtraWorkV2Invoice::generateInvoiceNumber()`** is a third generator on the model.

**A human can overwrite the number after creation**, and `update()` validates it as
`sometimes|string|max:50` with **no `unique` rule** — unlike `store()`. A PUT can therefore
set a number that duplicates an existing invoice.

## 4.7 Who may do any of this

The permission model is role-only. Four permission systems exist; three are decorative:

| System | Enforced? |
|---|---|
| `role_permissions` (bitwise, by role) | **YES — the only real gate** |
| `user_module_overrides` | NO — never read by any gate |
| `user_granular_permissions` | NO — served to the SPA as UI hints |
| `user_customer_building_permissions` | PARTLY — row filtering in four controllers; the middleware ignores it |

An administrator can open a user, tick boxes, save, get a success message, and change
nothing. `DATA` User 153's override restricts `extra_works` to mask 3 while their role
grants 255 — the override loses silently.

**The labels also lie.** The enforced table defines `32=export, 64=import, 128=admin`; the
display service defines `32=restore, 64=export, 128=manage`. Both vocabularies ship, so the
permission an operator reads is not necessarily the one the middleware enforces.

Two structural authorisation facts worth stating plainly:

- **A location manager can mint an admin.** `POST /admin/users` is gated on `users,create`;
  `role_id` is validated as `exists:roles,id` with no level comparison. V2 found this is
  worse than first reported — `customer_manager`, a *customer-type* role, also holds
  `users=23`.
- **No audit log is written for any permission, role or UCB change.** `ActivityLogger` is
  never called from the three relevant controllers.

Separately, the `/api/admin` prefix group carries no middleware of its own, so anything
inside it lacking its own `ucb.permission` is open to every authenticated user — including
**all 12 `/admin/reports/*` PDF and Excel endpoints**, which compute revenue from
`status_id = 9`, and the whole `/admin/worker-hours/*` group. *(Not a leak: the seven role
dashboards derive their scope from the caller's own `role_id`, so a customer calling
`/admin/dashboard` still gets customer-scoped numbers. Stated explicitly so nobody
"fixes" it wrongly.)*

---

# PART 5 — EVERY FIELD ON THE SPINE: CONNECTED OR DEAD

"Connected" means something reads it for a decision, a total, a filter or a document.
"Display-only" means it is read, but only to be printed on a screen — it gates nothing.
"DEAD" means nothing reads it at all.

## 5.1 `extra_works`

| Field | Verdict | What reads it / why it is dead |
|---|---|---|
| `status_id` | **CONNECTED — the most load-bearing field in the system** | The billing gate (8), the billed flag (9), the list's soft-delete of 9, every dashboard bucket |
| `type` | **CONNECTED** | Melding vs Extra Work: route prefix, permission module, notification type, deep link, dashboard date choice |
| `customer_id`, `building_id` (via `extra_work_customer_building`), `customer_department_id`, `customer_works_type_id` | **CONNECTED** | Scoping, grouping in the invoice picker, reports |
| `title` | **CONNECTED — and overloaded** | Becomes the invoice line `description`. Also the **only** store of the `condition` (op/voor/na) value, recovered by regex |
| `invoice_id` | **DEAD IN PRACTICE** | Written by one rarely-used path (`addItem`), cleared by four, never written by the bulk path that created every live invoice. NULL on all 37 status-9 works. Selected by a SQL view that nothing reads |
| `invoice_date` | **DEAD IN PRACTICE** | Same as above. When a screen says "invoice date" it means `invoices.invoice_date` through the join |
| `hours_planed` | **Display-only** | Six writers, zero decision-readers. Caps, warns and blocks nothing; touches no price. Live: work 474 has `hours_planed = 1.00` against 13.5 distributed hours, no warning anywhere |
| `hours_worked` | **DEAD** | NULL on all 39 live v1 works. Its only real consumer is `getRemainingHours()`, which is itself structurally zero |
| `upload_is_required` | **DEAD** | Appears only in `$fillable`, `$casts`, one report echo and two SQL views — never in an `if`. Not in the config field allow-list, so no live endpoint can persist it. 0 of 76 records has it set |
| `notes_is_required` | **DEAD** | Identical to the above |
| `file_1` … `file_4` | **DEAD** | Nothing reads or writes them |
| `created_by`, `planed_by`, `started_by`, `completed_by`, `approved_by`, `archive_*_by`, `drafted_by` | **CONNECTED but mistyped** | All `VARCHAR(100)` holding `"Name (Role)"`. Three code paths compare `created_by` to an integer user id, so "the creator can see their own record" never fires and the creator never gets unread-comment rows |
| `planed_at`, `started_at`, `completed_at`, `approved_at` | **CONNECTED (written), display-only (read)** | Stamped by the server; never compared to the clock anywhere |
| `deadline_at` | **CONNECTED** | The *only* date compared to `now()`, and only in dashboards and the weekly plan — never inside the Extra Work area |
| `customer_start_date`, `planed_start_at`, `planed_end_at`, `requested_at` | **Display-only** | Never compared to the clock. `requested_at` is additionally *wrong* for batch-created records: `batchStore` writes the scheduled slot, not the request time, so it can precede `created_at` by weeks |
| archive family (`archive_requested_*`, `archive_approved_*`, `archive_rejected_*`) | **CONNECTED** | Drive the archive UI; back-filled and cleared by `approveArchive` |
| `group_id` + group columns | **CONNECTED** | Grouped views, bulk operations |

## 5.2 `invoices` / `invoice_items` / `invoiceable_items`

| Field | Verdict | Notes |
|---|---|---|
| `invoice_items.extra_work_id` | **CONNECTED — the only real EW↔invoice link** | Every read from a work to its invoice goes through it (`hasOneThrough`) |
| `invoice_items.invoiceable_item_id` + `source_type` | **CONNECTED (v2/project paths only)** | The table is shared; v1 never uses the invoiceable side |
| `invoice_items.amount` | **CONNECTED** | `total_products_cost` — products only |
| `invoice_items.tax_rate` | **CONNECTED but falsified** | Hardcoded `0.21`, overwriting the real per-line rate |
| `invoice_items.quantity` / `unit_name` | **CONNECTED but wrong for multi-product works** | Taken from the first product only |
| `invoices.invoice_number` | **CONNECTED** | Client-supplied on the v1 path; overwritable later with no uniqueness check |
| `invoices.status` | **CONNECTED** | `draft` → `sent` → `cancelled`; gates every item mutation |
| `invoices.sent_at`, `pdf_path`, `pdf_generated_at` | **CONNECTED** | Written by `sendInvoice` |
| `invoices.period_start` / `period_end` | **DEAD IN PRACTICE** | Never written by any creation path; NULL on all live invoices; only the PDF reads them, and falls back to the month of `invoice_date` |
| `invoices.due_date` | **DEAD** | Never set, NULL in all live data. The PDF computes `invoice_date + 1 month` at render time — the payment term is a constant inside a Blade template, not data |
| `invoices.summary_*` and `discount_*` | **CONNECTED but incoherent** | A pure override that wins on PDF page 1, is ignored on page 2, and never reaches `total_amount` |
| `invoices.cancelled_at` | **CONNECTED (to nothing else)** | Set on cancel; releases nothing |
| `invoiceable_items.*` | **CONNECTED to the project path only** | 13 live rows, all type `project`; zero extra-work rows |

## 5.3 The hours and pricing tables

| Field | Verdict | Notes |
|---|---|---|
| `extra_work_employee_hours.total_cost` | **CONNECTED — but only to display** | Reaches formulas 2 and 5 and the reports; **never reaches an invoice** |
| `extra_work_employee_hours.hourly_rate` | **CONNECTED** | Snapshotted at creation; `0` when the employee has no rate |
| `overtime_types.multiplier` | **CONNECTED at write, stale at read** | Read live at save then discarded; later edits do not re-price |
| `extra_work_products.price` / `tax_rate` / `name` / `unit_id` / `category_id` | **CONNECTED** | The value snapshot. `tax_rate` is correct here and destroyed at the invoice |
| `extra_work_products.customer_product_id` | **Display-only** | Renders a link, skips duplicates on re-save. No total follows it back |
| `extra_work_products.hours_worked` | **DEAD as money** | Summed into a `total_hours` that no money formula uses |
| `extra_work_products.is_fixed_price` | **See 05** | Area-local |
| `product_price_history` | **DEAD TABLE** | No writer anywhere. Two routed endpoints for it point at a method and a relation that do not exist |
| `customer_product_versions` / `customer_product_prices` | **DEAD to the spine** | A real dated price book that extra works and invoicing never consult |
| `customer_products.start_date` / `end_date` / `is_active` | **Display-only** | No live row sets them |

## 5.4 Groups, files, comments

| Field | Verdict | Notes |
|---|---|---|
| `condition` (op / voor / na) | **NEVER PERSISTED** | No column, no config field, no payload key survives. Converted to a Dutch word and baked into the title string; every reader recovers it by regex |
| `extra_works_attachments.is_draft` | **CONNECTED but not a privacy control** | Draft photos render to every viewer, customer included, under a heading reading "Draft Images". It stages photos, gates deletion, and flips on approval |
| `extra_works_attachments.is_pre_file` | **CONNECTED** | Before/after classification — see 07 |
| `extra_work_groups.is_auto_generated` | **DEAD** | Written `true` always, read by nothing |
| `extra_work_groups.name` | **DEAD** | The writer always passes `null` |
| `extra_work_groups.building_id` | **DEAD as a read** | Written, relation exists, never called, no query filters on it |
| `extra_work_comments.mentioned_users` | **DEAD** | Written and validated, read by nothing |

---

# PART 6 — CONNECTIONS THAT SHOULD EXIST AND DO NOT

*This section describes gaps only. It does not propose fixes and does not design anything
for our system — that decision belongs to the owner and the architect, not to this
investigation.*

**1. A work knows nothing about its own invoice.**
`extra_works.invoice_id` and `invoice_date` exist, are fillable, are cast, and are selected
by a SQL view. The bulk path that produced every live invoice never writes them; one rarely
used path does; four paths clear them. The forward link is therefore NULL on all 37
invoiced works, and the model's `invoice()` relation routes *around* the column via
`hasOneThrough`. Two representations of one fact exist, and the authoritative one is the
indirect one.

**2. Cancelling an invoice does not release its works.**
Three of the five doors out of status 9 clear the work's links and return it to the billable
pool. Cancel — the only door available once an invoice has actually been sent — updates the
invoice row alone. There is no release, no credit note, no negative line, no
invoice-references-invoice column, and no route back to the pool. The V2 subsystem's cancel
path does release its items; the live v1 path does not. The two halves of the same product
disagree.

**3. Nothing connects a date to a billing period.**
`period_start` and `period_end` exist on `invoices` and are never written by any creation
path. No query, cutoff, window or rule decides which works belong together on an invoice;
an operator's manual selection does. The one place a real period is computed —
`BillingService`, writing `period_start`/`period_end`/`scheduled_date` onto staging rows
from the work's billing dates — serves a path that has produced zero extra-work rows.

**4. Labour is computed and then not carried.**
`extra_work_employee_hours.total_cost` is written, summed, displayed on the detail screen
and printed in reports, and the invoice line takes `total_products_cost` instead. The
comment `// Only products, not labor` marks the disconnection as deliberate, but nothing
downstream reconciles the two numbers, so the "grand total" a customer-facing screen shows
and the amount the customer is billed are different quantities with no stated relationship.

**5. The correct VAT rate is carried all the way to the boundary and then overwritten.**
Per-line `tax_rate` is resolved correctly from the customer product and is genuinely
heterogeneous in live data. `InvoiceController` writes the literal `0.21` over it. The
information exists, arrives, and is discarded one step from where it was needed.

**6. `hours_planed` is a budget with no consumer.**
Six writers, no reader that decides anything. The three functions that would have connected
it to behaviour — `canDistributeHours()`, `validateTotalHours()`, `getRemainingHours()` —
are respectively never called, never called, and structurally incapable of returning
anything but zero. The intent is visible in the code; the wiring was never made or was
deliberately removed (`// Hours validation removed per user request`).

**7. Nothing observes the passage of time.**
No date on an Extra Work is compared to the clock inside the Extra Work area, no scheduler
exists, and no `schedule:run` target exists anywhere for a host cron to call. A fully
translated `deadline_reminder` template exists in four languages and nothing sends it; four
more configured templates are likewise unreachable; the only endpoint with "schedule" in its
name returns `'mock_mode' => true` with the warning that the queue system is not
implemented. `ExtraWorkV2InvoiceService::checkOverdueInvoices()` is written correctly and
called by nobody, so the `overdue` status can never be reached. **An extra work that is
never touched again is never mentioned again.**

**8. Nothing escalates.**
The status fan-out notifies every UCB holder, every assignee, everyone in the same
department and every admin, equally, for every status change. That is a broadcast. No
notification is ever addressed to anyone *because* somebody else failed to act.

**9. Permission screens are not connected to permission enforcement.**
`user_module_overrides` and `user_granular_permissions` are written by admin CRUD screens
and read by no gate. Rows exist in live data that contradict what the system actually
enforces. Separately, the enforced bit vocabulary and the displayed bit vocabulary disagree,
and both ship.

**10. Changes to permissions, roles and scopes are not recorded anywhere.**
`ActivityLogger` is never called from `UsersController`,
`UserGranularPermissionsController` or `UserPermissionController`. Extra Works have an
activity trail; the authorisation system has none.

**11. The activity trail has holes exactly where money moves.**
Four bulk endpoints and the invoice-delete path use query-builder mass `update()`, which
fires no Eloquent events — so the un-invoicing of a work writes no activity row. `DATA`
Work 448's log contains two consecutive `8 → 9` rows with no `9 → 8` between them: the
record returned to 8 invisibly. The `4 → 8` archive step is not logged as a status change
either.

**12. Several declared links are inert.**
`grades_inspections.extra_work_id` is a real nullable FK with a real foreign key, fillable,
cast, with a `belongsTo` and a `has_extra_work` accessor — and nothing ever assigns it, so a
failed inspection cannot create or attach an Extra Work. `ExtraWork::tasks()` points at
`TicketTask`, a class that no longer exists over a table that was dropped — calling it
fatals. `app/Models/CustomerExtrawork.php` is a zero-byte file while a
`CustomerExtraworksController` exists.

**13. The status vocabulary is shared with two other systems, and the collision is live.**
`t_ticket_status` serves tickets (removed), Extra Work v1 and ExtraWorkV2. Status **7** is
labelled "Gefactureerd" but belongs to V2; v1's invoiced status is **9**, whose label is the
untranslated lowercase string `invoiced`. `DATA` On 2026-06-04 a single authenticated actor
moved roughly 25 v1 works to status 7 and back to 9 — using the status that *reads*
"Gefactureerd" rather than the one that *means* it. The naming collision produced a real
operator error on live records.

---

# PART 7 — COULD NOT DETERMINE

Honest gaps. Each says what would close it.

## 7.1 The six assumptions underneath the whole corpus

These were relied on by every agent and tested by none. They are the correct starting point
for anyone who needs more certainty than this investigation provides.

1. **The true DDL of the core tables is unknown.** There is no `CREATE TABLE` migration for
   `extra_works`, `extra_works_attachments`, `extra_work_comments`, `extra_work_products`,
   `extra_work_employee_hours`, `employee_hourly_rates`, `overtime_types`,
   `employee_contracts`, `role_permissions`, `modules`, `user_module_overrides` or
   `user_customer_building_permissions`; `products` and `customer_products` have empty stub
   migrations. **Every "IF NULL/EMPTY" statement in all nine reports is inferred from model
   casts plus observed values, not read from the schema** — as is every claim about
   `ON DELETE` behaviour on those tables. *Closes with:* one `SHOW CREATE TABLE` sweep or a
   `mysqldump --no-data`.
2. **Nobody verified that the cloned code is the deployed code.** Every "CODE says X but
   DATA shows Y" contradiction has this as an unexamined alternative explanation.
   *Closes with:* a deployed-version endpoint or a git ref from the server.
3. **At least three clients write to this database and only the admin SPA was read.** A
   hard-coded `https://api.osius.nl` POST exists in `meldings/detail.jsx`; live attachment
   rows carry `uploaded_from: "portal"` (served from `portal.osius.nl`) and
   `uploaded_from: "admin"` rows described as mobile uploads. **Every "no code does X" claim
   in this corpus is scoped to two repositories.** *Closes with:* access to the portal and
   mobile clients.
4. **Every count excludes soft-deleted rows**, because no reachable endpoint exposes trashed
   records. This silently underpins the 76-record population, "0 records have the
   requirement flags", "statuses 5 and 6 never held a v1 row", the 13 invoiceable items and
   the 15 empty groups. *Closes with:* direct database access.
5. **The observed 500s are environment-specific.** The `QueryException` handler returns SQL
   detail only when the app is not `production`. Behaviour on a production deploy differs.
6. **A host-level cron cannot be excluded.** *This one was narrowed during the
   investigation:* both committed systemd units were read (`crm-laravel.service` runs
   `artisan serve`; `crm-socket.service` runs `node server.js` — neither is a timer),
   `deploy.sh` contains no cron/schedule/queue reference, no `.timer` or crontab file exists
   in either repo, and **`schedule:run` appears nowhere in the repositories at all**. So even
   if an unread host crontab exists, there is no scheduler target defined for it to call and
   no scheduled task for it to run. *Residual:* an ad-hoc host script calling an HTTP
   endpoint cannot be ruled out from here. *Closes with:* `crontab -l` on the server.

## 7.2 Specific unresolved items

- **The `sent_at` coupling — resolved as far as the evidence allows, but not proven.**
  Works flipped `7 → 9` at the exact second their invoice was sent; the works of a
  still-draft invoice did not move. V2 exhausted the code search space: the `Invoice` model
  has no `boot()`/`booted()`/`static::` hook; there is no invoice observer, event, listener
  or job anywhere; only two backend writers of status 9 exist and both are inside invoice
  *creation*; the single frontend writer is an unrelated zero-amount branch; and
  `sendInvoice()` touches no Extra Work. Decisively, the `7 → 9` rows **have activity rows**
  (so they were per-record model saves, not mass updates) and carry `user_id = 128` — the
  same actor who set them to 7 sixteen seconds earlier. `INFERRED`: one person working
  invoice-by-invoice, stamping "Gefactureerd" with the wrong status, sending, then
  correcting — two legs of one manual routine, not cause and effect. *Closes with:* the
  activity rows for all ~25 works in that minute, and the web-server access log for user
  128. Neither is reachable read-only.
  **Report 03's wording should be corrected regardless of mechanism:** "nothing about the
  works changes when an invoice is sent" is true of `sendInvoice()`'s code and false of the
  observed system.
- **Statuses 5 and 6 are untested-negative, not disproven.** Status 7 was found on live v1
  rows, so the "V2 vocabulary only" claim is contradicted for 7. 5 and 6 have simply never
  been observed on a v1 row.
- **The live population is 76 distinct ids, not 78, and three sources disagree.** The
  `?statuses=` filter leaks: `?statuses=2` returns a record whose `status_id` is 1, and
  `?statuses=1,2` returns one whose status is 4 — a group-header OR-condition. Every count
  derived from that filter, including the per-status table in report 01, is inflated. The
  statistics endpoint reports different numbers again. Cite the range and the reason, not a
  single figure.
- **The PDF is three pages, not two.** The page-1-versus-page-2 divergence in §4.5 is
  established from the template; the third page was not separately mapped.
- **Not swept at all, and money-shaped:** `ContinuousWork*` (which demonstrably touches
  Extra Work v2), `ContractRevision`/`ContractRevisionLine`, `ContractLinePlanning`,
  `BuildingCostDistribution`, `BuildingServiceBudget`, `CustomerServiceAllocation`. These
  were outside every agent's named list and need an owner.
- **Unchecked:** whether invoice list queries join `Customer`/`Building` without
  `withTrashed()`, which would make a soft-deleted customer's invoices vanish from lists.
- **ExtraWorkV2 was mapped only where its logic differs from v1.** It is not covered here to
  v1's depth, by design.

---

# PART 8 — WHERE THIS PROMPT WAS WRONG

The brief asked to be checked rather than believed. It was checked. The pattern across all
six flagged beliefs is that **the brief was reliably right about mechanisms and
consistently too gentle about consequences** — and wrong once, on a point that only live
data could settle.

| # | The brief's belief | Verdict |
|---|---|---|
| 1 | `hours_planed` display-only; `canDistributeHours()` never called; `getRemainingHours()` does not use it | **CONFIRMED ×3 — and understated.** `getRemainingHours()` does not merely ignore `hours_planed`; it returns 0 unconditionally, because its first term is a property that does not exist on the model. `canDistributeHours()` would refuse *every* distribution if revived. A third dead guard, `validateTotalHours()`, was not in the brief at all |
| 2 | Cancelling sets `status` + `cancelled_at` and nothing else; no credit note or reversal anywhere | **CONFIRMED on mechanism — badly understated on consequence.** The issue is not the absent credit note; it is that cancellation permanently destroys billability. The works stay at 9, keep lines pointing at a cancelled invoice, and can never be re-billed through the UI. The V2 subsystem gets this right, which makes it an inconsistency rather than an omission |
| 3 | v1 statuses 1,2,3,4,8,9; **5 is archive-rejected and unused** | **WRONG, in three places.** 5 is `internal_approval`, not archive-rejected. 5, 6 and 7 are ExtraWorkV2 vocabulary sharing v1's lookup table. Status **7** carries the label "Gefactureerd" while v1's invoiced status is **9**, labelled with the untranslated lowercase `invoiced`. And status 7 *is* reachable on v1 rows — live data shows ~25 of them. The v1 frontend even renders an unreachable `case 5:` "Archive Rejected" branch |
| 4 | Completion requirements enforced in the frontend only | **CONFIRMED — and stronger than believed.** They are not merely unenforced; they cannot be persisted at all, because neither name is in the config field allow-list. 0 of 76 live records has either set |
| 5 | `invoiceable_items` holds no extra-work rows, so v1 bypasses it | **CONFIRMED.** One nuance: `invoice_items` carries both `extra_work_id` and `invoiceable_item_id` with a `source_type` discriminator, so the table is shared infrastructure — v1 simply never uses the invoiceable side |
| 6 | Coordinators are users, workers are employees, matched by lowercased email | **HALF RIGHT.** The user/employee split is correct. But the lowercased-email match is frontend-only — one React effect in the Plan modal — and is *not* the User↔Employee link, which is the `users.employee_id` FK. And the word "coordinator" appears **nowhere in the backend PHP**: coordinator status changes no behaviour at all. The email match does have a money consequence — a coordinator whose two email records differ in any way is silently never added as a worker, so gets no hours row |

**A seventh error, in the brief's own tier-2 instructions.** It told the pricing agent that
"the approval and archive modals both show editable totals". They do not — both are
read-only display, and `ExtraWorkApprovalModal.jsx`'s own state comment reads
`Financials state (READ-ONLY)`. The real hand-edit surfaces are elsewhere: the Financials
tab line editor, the invoice line editor, and the invoice "Overzicht" `summary_*` override.

**On the count of invoice-creation paths**, the brief said "at least three". That is right,
and deliberately hedged: there are three *mechanisms* (A/B/C) and four *route surfaces*.

## Where the prompt was right, and it mattered

- **"Almost everything is connected to something else and the connections are the actual
  product."** Correct, and the reason a field inventory failed. The most valuable findings
  in this investigation are all edges, not nodes: labour computed and not carried, VAT
  resolved and overwritten, cancel that releases nothing, a group path that skips approval
  and lands in the billing pool.
- **"Finding a dead field is a real result."** Correct. The dead set is large and
  load-bearing: `invoice_id`, `invoice_date`, `period_start`/`period_end`, `due_date`,
  `hours_worked`, `upload_is_required`, `notes_is_required`, `file_1..4`,
  `product_price_history`, `mentioned_users`, and `condition` — which is not merely dead but
  never persisted at all.
- **Running A3 as its own agent on the seam.** Justified. A1 and A2 each described their own
  side correctly and neither would have produced §3.2 or Part 6.
- **Insisting on live data over self-report.** Decisive. Belief 3 was only falsifiable
  against the database, the price-snapshot proof came from comparing a live line to its live
  catalogue entry, and the `?statuses=` leak that undermines every published count would
  have been invisible from code alone.
